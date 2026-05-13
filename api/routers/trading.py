import asyncio
import logging
import time

from fastapi import APIRouter, Query, Request

from api.connection_manager import push_signal_event, set_symbol_priority, _PRIORITY_POSITION, _PRIORITY_WATCHLIST
from api.routers.models import (
    PortfolioImportRequest, TCAAnalyzeRequest, TCABatchRequest,
    TCAExecutionRecommendRequest, TradingBuyRequest, TradingSellRequest,
)
from api.utils import json_response as _json_response
from api.utils import get_trading, rate_limiter, safe_error

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_SINGLE_POSITION_PCT = 0.20


@router.get("/trading/account")
async def get_trading_account(request: Request):
    try:
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        return _json_response(True, data=trading.get_account_info())
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/trading/buy")
async def trading_buy(
    request: Request,
    body: TradingBuyRequest,
):
    try:
        from api.routers.models import BuyOrderRequest
        from core.data_fetcher import SmartDataFetcher
        from core.market_detector import MarketDetector

        validated = BuyOrderRequest(symbol=body.symbol, price=body.price, shares=body.shares, name=body.name, market=body.market)
        symbol = validated.symbol
        price = validated.price
        shares = validated.shares
        name = validated.name
        market = validated.market
        if not market:
            market = MarketDetector.detect(symbol)
        if not name:
            from core.stock_search import get_stock_name
            name = get_stock_name(symbol) or symbol
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        fetcher: SmartDataFetcher = request.app.state.fetcher
        rt = await fetcher.get_realtime(symbol, market)
        market_price = rt.get("price", 0) if rt else 0

        from core.orders import Order, OrderSide, OrderType
        from core.risk_manager import EnhancedRiskManager

        account = trading.get_account_info() if hasattr(trading, "get_account_info") else {}
        total_assets = account.get("total_assets", 0)
        available_cash = account.get("cash", 0)
        positions = trading.get_positions() if hasattr(trading, "get_positions") else {}
        pos_dict = {}
        if isinstance(positions, dict):
            for sym, pos in positions.items():
                mv = getattr(pos, "market_value", 0) if not isinstance(pos, dict) else pos.get("market_value", 0)
                pos_dict[sym] = {"market_value": mv}

        order_value = shares * (market_price if market_price > 0 else price)
        if total_assets <= 0:
            return _json_response(False, error="账户资产信息异常，无法执行交易")
        if (order_value / total_assets) > MAX_SINGLE_POSITION_PCT:
            return _json_response(False, error=f"单笔仓位超过{MAX_SINGLE_POSITION_PCT*100:.0f}%限制")

        risk_order = Order(
            order_id=f"pre_trade_{symbol}_{int(time.time())}",
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=shares,
            price=market_price if market_price > 0 else price,
        )
        risk_ctx = {
            "total_assets": total_assets,
            "cash": available_cash,
            "current_positions": pos_dict,
        }
        risk_manager = getattr(request.app.state, "risk_manager", None)
        if risk_manager is None:
            risk_manager = EnhancedRiskManager(initial_capital=total_assets if total_assets > 0 else 1000000)
            request.app.state.risk_manager = risk_manager

        risk_ok, risk_reason = risk_manager.check_order(risk_order, risk_ctx)
        if not risk_ok:
            ws_manager = getattr(request.app.state, "ws_manager", None)
            if ws_manager:
                asyncio.create_task(ws_manager.broadcast({
                    "type": "risk_alert",
                    "data": {"symbol": symbol, "action": "buy", "reasons": [risk_reason]},
                    "ts": int(time.time() * 1000),
                }))
            return _json_response(False, error=f"风控拦截: {risk_reason}")

        result = trading.execute_buy(
            symbol=symbol, name=name, market=market, price=price,
            shares=shares, stop_loss=body.stop_loss, take_profit=body.take_profit,
            strategy=body.strategy, market_price=market_price,
        )
        if result.get("success"):
            await set_symbol_priority(symbol, _PRIORITY_POSITION)
            fill_price = result.get("price", price)
            logger.info(
                "Trade executed",
                extra={
                    "event": "trade_buy",
                    "symbol": symbol,
                    "price": fill_price,
                    "shares": shares,
                    "strategy": body.strategy or "",
                    "account_value": result.get("account_value", 0),
                },
            )
            asyncio.create_task(push_signal_event(
                symbol=symbol,
                strategy=body.strategy or "",
                signal_type="buy",
                score=1.0,
                price=fill_price,
            ))
        return _json_response(result.get("success", False), data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/trading/reset")
async def trading_reset(request: Request):
    try:
        trading = get_trading(request)
        if trading is None:
            return _json_response(False, error="交易引擎未初始化")
        if hasattr(trading, "reset_account"):
            trading.reset_account()
        elif hasattr(trading, "reset"):
            trading.reset()
        risk_manager = getattr(request.app.state, "risk_manager", None)
        if risk_manager is not None and hasattr(risk_manager, "reset"):
            risk_manager.reset()
        return _json_response(True, data={"message": "交易账户已重置"})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/trading/sell")
async def trading_sell(
    request: Request,
    body: TradingSellRequest,
):
    try:
        from core.data_fetcher import SmartDataFetcher
        from core.market_detector import MarketDetector

        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        symbol = body.symbol
        price = body.price
        sell_shares = body.shares
        if sell_shares is None:
            positions = trading.get_positions()
            pos = positions.get(symbol)
            sell_shares = pos.shares if pos else 0
        if sell_shares <= 0:
            return _json_response(False, error="无持仓或卖出数量无效")
        fetcher: SmartDataFetcher = request.app.state.fetcher
        market = MarketDetector.detect(symbol)
        rt = await fetcher.get_realtime(symbol, market)
        market_price = rt.get("price", 0) if rt else 0

        from core.orders import Order, OrderSide, OrderType
        from core.risk_manager import EnhancedRiskManager

        account = trading.get_account_info() if hasattr(trading, "get_account_info") else {}
        total_assets = account.get("total_assets", 0)
        sell_available_cash = account.get("cash", 0)
        positions_map = trading.get_positions() if hasattr(trading, "get_positions") else {}
        pos_dict = {}
        if isinstance(positions_map, dict):
            for sym, pos in positions_map.items():
                mv = getattr(pos, "market_value", 0) if not isinstance(pos, dict) else pos.get("market_value", 0)
                pos_dict[sym] = {"market_value": mv}

        sell_order_value = sell_shares * (market_price if market_price > 0 else price)

        if total_assets <= 0:
            return _json_response(False, error="账户资产信息异常，无法执行交易")

        risk_order = Order(
            order_id=f"pre_trade_{symbol}_sell_{int(time.time())}",
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=sell_shares,
            price=market_price if market_price > 0 else price,
        )
        risk_ctx = {
            "total_assets": total_assets,
            "cash": sell_available_cash,
            "current_positions": pos_dict,
        }
        risk_manager = getattr(request.app.state, "risk_manager", None)
        if risk_manager is None:
            risk_manager = EnhancedRiskManager(initial_capital=total_assets)
            request.app.state.risk_manager = risk_manager

        risk_ok, risk_reason = risk_manager.check_order(risk_order, risk_ctx)
        if not risk_ok:
            ws_manager = getattr(request.app.state, "ws_manager", None)
            if ws_manager:
                asyncio.create_task(ws_manager.broadcast({
                    "type": "risk_alert",
                    "data": {"symbol": symbol, "action": "sell", "reasons": [risk_reason]},
                    "ts": int(time.time() * 1000),
                }))
            return _json_response(False, error=f"风控拦截: {risk_reason}")

        result = trading.execute_sell(
            symbol=symbol, price=price, reason=body.reason,
            shares=sell_shares, market_price=market_price,
        )
        if result.get("success"):
            positions = trading.get_positions()
            if symbol not in positions:
                await set_symbol_priority(symbol, _PRIORITY_WATCHLIST)
            fill_price = result.get("price", price)
            logger.info(
                "Trade executed",
                extra={
                    "event": "trade_sell",
                    "symbol": symbol,
                    "price": fill_price,
                    "shares": sell_shares,
                    "strategy": body.reason or "",
                    "account_value": result.get("account_value", 0),
                },
            )
            asyncio.create_task(push_signal_event(
                symbol=symbol,
                strategy=body.reason or "",
                signal_type="sell",
                score=1.0,
                price=fill_price,
            ))
        return _json_response(result.get("success", False), data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/trading/history")
async def get_trading_history(request: Request, limit: int = Query(100)):
    try:
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        return _json_response(True, data=trading.get_trade_history(limit))
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/trading/export")
async def export_trading_portfolio(request: Request):
    try:
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        portfolio = trading.export_portfolio()
        return _json_response(True, data=portfolio)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/trading/import")
async def import_trading_portfolio(request: Request, body: PortfolioImportRequest):
    try:
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        result = trading.import_portfolio(body.data)
        return _json_response(result.get("success", False), data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/trading/daily-pnl")
async def get_daily_pnl(request: Request, limit: int = Query(30)):
    try:
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        return _json_response(True, data=trading.get_daily_pnl(limit))
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/trading/record-pnl")
async def record_daily_pnl(request: Request):
    try:
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        daily = trading.record_daily_pnl()
        return _json_response(True, data=daily)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/trading/analytics")
@rate_limiter(max_calls=20, time_window=60.0)
async def get_trading_analytics(request: Request):
    try:
        import numpy as np

        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        history_result = trading.get_trade_history(limit=1000)
        history = history_result.get("trades", []) if isinstance(history_result, dict) else []
        if not history:
            return _json_response(True, data={
                "total_trades": 0,
                "message": "暂无交易记录",
            })

        sells = [t for t in history if t.get("action") == "sell" and "pnl" in t]
        buys = [t for t in history if t.get("action") == "buy"]

        total_trades = len(sells)
        if total_trades == 0:
            return _json_response(True, data={
                "total_trades": len(history),
                "buy_count": len(buys),
                "sell_count": 0,
                "message": "暂无已平仓交易",
            })

        pnls = [float(t.get("pnl", 0)) for t in sells]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        total_pnl = sum(pnls)
        win_rate = len(wins) / total_trades if total_trades > 0 else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf") if wins else 0.0
        expectancy = (win_rate * avg_win + (1 - win_rate) * avg_loss) if total_trades > 0 else 0.0

        max_consec_wins = 0
        max_consec_losses = 0
        current_wins = 0
        current_losses = 0
        for p in pnls:
            if p > 0:
                current_wins += 1
                current_losses = 0
                max_consec_wins = max(max_consec_wins, current_wins)
            elif p < 0:
                current_losses += 1
                current_wins = 0
                max_consec_losses = max(max_consec_losses, current_losses)
            else:
                current_wins = 0
                current_losses = 0

        cumulative_pnl = np.cumsum(pnls)
        peak = np.maximum.accumulate(cumulative_pnl)
        drawdown = cumulative_pnl - peak
        max_dd = float(np.min(drawdown)) if len(drawdown) > 0 else 0.0

        pnl_std = float(np.std(pnls)) if len(pnls) > 1 else 0.0
        sharpe = float(np.mean(pnls) / pnl_std * np.sqrt(252)) if pnl_std > 1e-12 else 0.0

        best_trade = max(sells, key=lambda t: float(t.get("pnl", 0))) if sells else {}
        worst_trade = min(sells, key=lambda t: float(t.get("pnl", 0))) if sells else {}

        symbol_pnl = {}
        for t in sells:
            sym = t.get("symbol", "unknown")
            symbol_pnl[sym] = symbol_pnl.get(sym, 0.0) + float(t.get("pnl", 0))

        top_winners = sorted(symbol_pnl.items(), key=lambda x: x[1], reverse=True)[:5]
        top_losers = sorted(symbol_pnl.items(), key=lambda x: x[1])[:5]

        return _json_response(True, data={
            "total_trades": total_trades,
            "buy_count": len(buys),
            "sell_count": total_trades,
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(win_rate, 4),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(min(profit_factor, 999.0), 2),
            "expectancy": round(expectancy, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_dd, 2),
            "max_consecutive_wins": max_consec_wins,
            "max_consecutive_losses": max_consec_losses,
            "best_trade": {
                "symbol": best_trade.get("symbol", ""),
                "pnl": round(float(best_trade.get("pnl", 0)), 2),
            },
            "worst_trade": {
                "symbol": worst_trade.get("symbol", ""),
                "pnl": round(float(worst_trade.get("pnl", 0)), 2),
            },
            "top_winners": [{"symbol": s, "pnl": round(p, 2)} for s, p in top_winners],
            "top_losers": [{"symbol": s, "pnl": round(p, 2)} for s, p in top_losers],
        })
    except Exception as e:
        logger.error("Trading analytics error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/tca/analyze")
async def tca_analyze_trade(request: Request, body: TCAAnalyzeRequest):
    try:
        from core.tca import Side, TCAEngine, TradeAnalysis

        side = Side.BUY if body.side == "buy" else Side.SELL
        trade = TradeAnalysis(
            symbol=body.symbol,
            strategy_name=body.strategy_name,
            side=side,
            decision_price=body.decision_price,
            arrival_price=body.arrival_price,
            execution_price=body.execution_price,
            vwap_benchmark=body.vwap_benchmark or body.arrival_price,
            twap_benchmark=body.twap_benchmark or body.arrival_price,
            quantity=body.quantity,
            execution_timestamp=body.execution_timestamp,
        )
        engine = TCAEngine()
        analysis = engine.analyze_trade(trade)
        return _json_response(True, data={
            "symbol": body.symbol,
            "side": body.side,
            "cost_metrics": {k: round(v, 8) for k, v in analysis.items()},
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/tca/batch")
async def tca_analyze_batch(request: Request, body: TCABatchRequest):
    try:
        from core.tca import Side, TCAEngine, TradeAnalysis

        engine = TCAEngine()
        trades = []
        for t in body.trades:
            side = Side.BUY if t.side == "buy" else Side.SELL
            trades.append(TradeAnalysis(
                symbol=t.symbol,
                strategy_name=t.strategy_name,
                side=side,
                decision_price=t.decision_price,
                arrival_price=t.arrival_price,
                execution_price=t.execution_price,
                vwap_benchmark=t.vwap_benchmark or t.arrival_price,
                twap_benchmark=t.twap_benchmark or t.arrival_price,
                quantity=t.quantity,
                execution_timestamp=t.execution_timestamp,
            ))

        batch_result = engine.analyze_batch(trades)
        strategy_attr = engine.attribute_by_strategy(trades)
        time_attr = engine.attribute_by_time_period(trades)

        return _json_response(True, data={
            "summary": {
                "total_trades": batch_result.total_trades,
                "total_cost": batch_result.total_cost,
                "avg_implementation_shortfall": batch_result.avg_implementation_shortfall,
                "avg_market_impact": batch_result.avg_market_impact,
                "avg_vwap_slippage": batch_result.avg_vwap_slippage,
                "cost_breakdown": batch_result.cost_breakdown,
            },
            "strategy_attribution": [
                {
                    "strategy": a.bucket,
                    "avg_is": a.avg_implementation_shortfall,
                    "avg_mi": a.avg_market_impact,
                    "avg_vwap_slippage": a.avg_vwap_slippage,
                    "trade_count": a.trade_count,
                    "total_cost": a.total_cost,
                }
                for a in strategy_attr
            ],
            "time_attribution": [
                {
                    "period": a.bucket,
                    "avg_is": a.avg_implementation_shortfall,
                    "avg_mi": a.avg_market_impact,
                    "trade_count": a.trade_count,
                }
                for a in time_attr
            ],
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/tca/recommend")
async def tca_execution_recommendation(request: Request, body: TCAExecutionRecommendRequest):
    try:
        from core.tca import Side, TCAEngine, TradeAnalysis

        trading = getattr(request.app.state, "trading", None)
        if trading is None:
            return _json_response(True, data={
                "symbol": body.symbol,
                "recommended_algorithm": "VWAP",
                "recommended_time_window": "09:30-15:00",
                "recommended_slice_count": 6,
                "estimated_cost_bps": 0.0,
                "note": "Trading engine not available",
            })

        history = trading.get_trade_history()
        if not history or not history.get("trades"):
            return _json_response(True, data={
                "symbol": body.symbol,
                "recommended_algorithm": "VWAP",
                "recommended_time_window": "09:30-15:00",
                "recommended_slice_count": 6,
                "estimated_cost_bps": 0.0,
                "note": "No trade history available",
            })

        engine = TCAEngine()
        historical_trades = []
        for t in history["trades"]:
            if t.get("symbol") != body.symbol:
                continue
            side = Side.BUY if t.get("action") == "buy" else Side.SELL
            price = float(t.get("price", 0))
            if price <= 0:
                continue
            historical_trades.append(TradeAnalysis(
                symbol=body.symbol,
                strategy_name=t.get("strategy", "default"),
                side=side,
                decision_price=price,
                arrival_price=price,
                execution_price=price,
                vwap_benchmark=price,
                twap_benchmark=price,
                quantity=int(t.get("shares", 0)),
                execution_timestamp=t.get("time", ""),
            ))

        rec = engine.recommend_optimal_execution(body.symbol, historical_trades)
        return _json_response(True, data={
            "symbol": rec.symbol,
            "recommended_algorithm": rec.recommended_algorithm,
            "recommended_time_window": rec.recommended_time_window,
            "recommended_slice_count": rec.recommended_slice_count,
            "estimated_cost_bps": rec.estimated_cost_bps,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/journal")
async def add_journal_entry(request: Request):
    try:
        from core.trade_journal import JournalEntry, TradeJournal
        body = await request.json()
        entry = JournalEntry(
            symbol=body.get("symbol", ""),
            name=body.get("name", ""),
            trade_type=body.get("trade_type", "buy"),
            price=float(body.get("price", 0)),
            quantity=int(body.get("quantity", 0)),
            notes=body.get("notes", ""),
            tags=body.get("tags", []),
            emotion=body.get("emotion", ""),
            rating=int(body.get("rating", 0)),
        )
        if not entry.symbol:
            return _json_response(False, error="股票代码不能为空")
        journal = TradeJournal()
        entry_id = journal.add_entry(entry)
        return _json_response(True, data={"id": entry_id})
    except Exception as e:
        logger.error("Journal add error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/journal")
async def get_journal_entries(
    symbol: str | None = Query(None),
    tag: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    try:
        from core.trade_journal import TradeJournal
        journal = TradeJournal()
        entries = journal.get_entries(symbol=symbol, tag=tag, limit=limit, offset=offset)
        return _json_response(True, data={
            "entries": [
                {
                    "id": e.id,
                    "symbol": e.symbol,
                    "name": e.name,
                    "trade_type": e.trade_type,
                    "price": e.price,
                    "quantity": e.quantity,
                    "notes": e.notes,
                    "tags": e.tags,
                    "emotion": e.emotion,
                    "rating": e.rating,
                    "timestamp": e.timestamp,
                }
                for e in entries
            ],
            "count": len(entries),
        })
    except Exception as e:
        logger.error("Journal get error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.put("/journal/{entry_id}")
async def update_journal_entry(entry_id: int, request: Request):
    try:
        from core.trade_journal import TradeJournal
        body = await request.json()
        journal = TradeJournal()
        ok = journal.update_entry(entry_id, body)
        return _json_response(ok, data={"id": entry_id} if ok else None, error="更新失败" if not ok else None)
    except Exception as e:
        logger.error("Journal update error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.delete("/journal/{entry_id}")
async def delete_journal_entry(entry_id: int):
    try:
        from core.trade_journal import TradeJournal
        journal = TradeJournal()
        ok = journal.delete_entry(entry_id)
        return _json_response(ok, data={"id": entry_id} if ok else None, error="删除失败" if not ok else None)
    except Exception as e:
        logger.error("Journal delete error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/journal/stats")
async def get_journal_stats():
    try:
        from core.trade_journal import TradeJournal
        journal = TradeJournal()
        stats = journal.get_stats()
        return _json_response(True, data=stats)
    except Exception as e:
        logger.error("Journal stats error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/journal/analytics")
async def get_journal_analytics():
    try:
        from core.journal_analytics import analyze_journal
        from core.trade_journal import TradeJournal
        journal = TradeJournal()
        entries = journal.get_entries(limit=500)
        if not entries:
            return _json_response(True, data={"total_entries": 0})
        entry_dicts = []
        for e in entries:
            if isinstance(e, dict):
                entry_dicts.append(e)
            elif hasattr(e, "__dict__"):
                entry_dicts.append(e.__dict__)
            else:
                entry_dicts.append({"pnl": 0, "emotion": "neutral", "rating": 0, "timestamp": 0})
        report = analyze_journal(entry_dicts)
        return _json_response(True, data=report.to_dict())
    except Exception as e:
        logger.error("Journal analytics error: %s", e)
        return _json_response(False, error=safe_error(e))
