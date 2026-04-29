"""
QuantCore API路由模块
提供REST API和WebSocket实时推送
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Optional, Set

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect

from core.data_fetcher import SmartDataFetcher
from core.market_detector import MarketDetector
from core.market_hours import MarketHours

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        self.connections: list[WebSocket] = []
        self._subscriptions: dict[WebSocket, Set[str]] = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)
        self._subscriptions[ws] = set()

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)
        self._subscriptions.pop(ws, None)

    def subscribe(self, ws: WebSocket, symbols: list[str]):
        if ws in self._subscriptions:
            self._subscriptions[ws].update(symbols)

    def unsubscribe(self, ws: WebSocket, symbols: list[str]):
        if ws in self._subscriptions:
            self._subscriptions[ws] -= set(symbols)

    def get_all_subscribed_symbols(self) -> Set[str]:
        all_symbols: Set[str] = set()
        for symbols in self._subscriptions.values():
            all_symbols.update(symbols)
        return all_symbols


_manager = ConnectionManager()


def _is_trading_hours() -> bool:
    try:
        for market in ["A", "HK", "US"]:
            status = MarketHours.get_market_status(market)
            if status.get("is_open"):
                return True
    except Exception:
        pass
    return False


def _json_response(success: bool, data=None, error: str = ""):
    return {"success": success, "data": data, "error": error}


@router.get("/market/overview")
async def get_market_overview(request: Request):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        data = await fetcher.get_market_overview()
        return _json_response(True, data=data)
    except Exception as e:
        logger.error(f"Market overview error: {e}")
        return _json_response(False, error=str(e))


@router.get("/market/status")
async def get_market_status(request: Request):
    try:
        statuses = {}
        for market in ["A", "HK", "US"]:
            statuses[market] = MarketHours.get_market_status(market)
        return _json_response(True, data=statuses)
    except Exception as e:
        return _json_response(False, error=str(e))


@router.get("/stock/realtime/{symbol}")
async def get_stock_realtime(request: Request, symbol: str):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        data = await fetcher.get_realtime(symbol)
        if data:
            return _json_response(True, data=data)
        return _json_response(False, error="未获取到数据")
    except Exception as e:
        return _json_response(False, error=str(e))


@router.get("/stock/history/{symbol}")
async def get_stock_history(
    request: Request,
    symbol: str,
    period: str = Query("1y"),
    kline_type: str = Query("daily"),
    adjust: str = Query(""),
):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period, kline_type, adjust)
        if df.empty:
            return _json_response(False, error="无历史数据")
        result = df.to_dict("records")
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=str(e))


@router.get("/stock/fundamentals/{symbol}")
async def get_stock_fundamentals(request: Request, symbol: str):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        market = MarketDetector.detect(symbol)
        data = await fetcher.get_fundamentals(symbol, market)
        if data:
            return _json_response(True, data=data)
        return _json_response(False, error="无基本面数据")
    except Exception as e:
        return _json_response(False, error=str(e))


@router.get("/stock/indicators/{symbol}")
async def get_stock_indicators(
    request: Request,
    symbol: str,
    period: str = Query("1y"),
    kline_type: str = Query("daily"),
):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period, kline_type)
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足")
        from core.indicators import calc_all_indicators
        kline_data = df.to_dict("records")
        result = calc_all_indicators(kline_data)
        return _json_response(True, data=result)
    except Exception as e:
        logger.error(f"Indicators error: {e}")
        return _json_response(False, error=str(e))


@router.get("/watchlist")
async def get_watchlist(request: Request):
    try:
        from core.database import get_db
        db = get_db()
        watchlist = db.get_config("watchlist", [])
        if not isinstance(watchlist, list):
            watchlist = []

        fetcher: SmartDataFetcher = request.app.state.fetcher

        a_symbols = []
        other_symbols = []
        for symbol in watchlist:
            market = MarketDetector.detect(symbol)
            if market == "A":
                a_symbols.append(symbol)
            else:
                other_symbols.append(symbol)

        results = {}
        if a_symbols:
            batch_results = await fetcher.get_realtime_batch(a_symbols)
            results.update(batch_results)

        if other_symbols:
            tasks = [fetcher.get_realtime(s) for s in other_symbols]
            other_results = await asyncio.gather(*tasks, return_exceptions=True)
            for symbol, result in zip(other_symbols, other_results):
                if isinstance(result, dict):
                    results[symbol] = result

        return _json_response(True, data={"symbols": watchlist, "quotes": results})
    except Exception as e:
        logger.error(f"Watchlist error: {e}")
        return _json_response(False, error=str(e))


@router.post("/watchlist/add")
async def add_to_watchlist(request: Request, symbol: str = Query(...)):
    try:
        from core.database import get_db
        db = get_db()
        watchlist = db.get_config("watchlist", [])
        if not isinstance(watchlist, list):
            watchlist = []
        if symbol not in watchlist:
            watchlist.append(symbol)
            db.set_config("watchlist", watchlist)
        return _json_response(True, data=watchlist)
    except Exception as e:
        return _json_response(False, error=str(e))


@router.post("/watchlist/remove")
async def remove_from_watchlist(request: Request, symbol: str = Query(...)):
    try:
        from core.database import get_db
        db = get_db()
        watchlist = db.get_config("watchlist", [])
        if not isinstance(watchlist, list):
            watchlist = []
        if symbol in watchlist:
            watchlist.remove(symbol)
            db.set_config("watchlist", watchlist)
        return _json_response(True, data=watchlist)
    except Exception as e:
        return _json_response(False, error=str(e))


@router.get("/search")
async def search_stocks(request: Request, q: str = Query(...), limit: int = Query(10)):
    try:
        from core.stock_search import search_stocks as do_search
        results = do_search(q, limit=limit)
        return _json_response(True, data=results)
    except Exception as e:
        return _json_response(False, error=str(e))


@router.get("/trading/account")
async def get_trading_account(request: Request):
    try:
        trading = request.app.state.trading
        return _json_response(True, data=trading.get_account_info())
    except Exception as e:
        return _json_response(False, error=str(e))


@router.post("/trading/buy")
async def trading_buy(
    request: Request,
    symbol: str = Query(...),
    name: str = Query(""),
    market: str = Query(""),
    price: float = Query(...),
    shares: int = Query(...),
    stop_loss: float = Query(0),
    take_profit: float = Query(0),
    strategy: str = Query("manual"),
):
    try:
        if not market:
            market = MarketDetector.detect(symbol)
        if not name:
            from core.stock_search import get_stock_name
            name = get_stock_name(symbol) or symbol
        trading = request.app.state.trading
        fetcher: SmartDataFetcher = request.app.state.fetcher
        rt = await fetcher.get_realtime(symbol, market)
        market_price = rt.get("price", 0) if rt else 0
        result = trading.execute_buy(
            symbol=symbol, name=name, market=market, price=price,
            shares=shares, stop_loss=stop_loss, take_profit=take_profit,
            strategy=strategy, market_price=market_price,
        )
        return _json_response(result.get("success", False), data=result)
    except Exception as e:
        return _json_response(False, error=str(e))


@router.post("/trading/sell")
async def trading_sell(
    request: Request,
    symbol: str = Query(...),
    price: float = Query(...),
    shares: Optional[int] = Query(None),
    reason: str = Query("manual"),
):
    try:
        trading = request.app.state.trading
        fetcher: SmartDataFetcher = request.app.state.fetcher
        market = MarketDetector.detect(symbol)
        rt = await fetcher.get_realtime(symbol, market)
        market_price = rt.get("price", 0) if rt else 0
        result = trading.execute_sell(
            symbol=symbol, price=price, reason=reason,
            shares=shares, market_price=market_price,
        )
        return _json_response(result.get("success", False), data=result)
    except Exception as e:
        return _json_response(False, error=str(e))


@router.get("/trading/history")
async def get_trading_history(request: Request, limit: int = Query(100)):
    try:
        trading = request.app.state.trading
        return _json_response(True, data=trading.get_trade_history(limit))
    except Exception as e:
        return _json_response(False, error=str(e))


@router.get("/config/{key}")
async def get_config(request: Request, key: str):
    try:
        from core.database import get_db
        db = get_db()
        value = db.get_config(key)
        return _json_response(True, data=value)
    except Exception as e:
        return _json_response(False, error=str(e))


@router.post("/config/{key}")
async def set_config(request: Request, key: str, value: str = Query(...)):
    try:
        from core.database import get_db
        db = get_db()
        db.set_config(key, value)
        return _json_response(True)
    except Exception as e:
        return _json_response(False, error=str(e))


@router.websocket("/ws/realtime")
async def websocket_realtime(ws: WebSocket):
    await _manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action", "")
                symbols = msg.get("symbols", [])
                if action == "subscribe" and symbols:
                    _manager.subscribe(ws, symbols)
                elif action == "unsubscribe" and symbols:
                    _manager.unsubscribe(ws, symbols)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        _manager.disconnect(ws)
    except Exception:
        _manager.disconnect(ws)


_last_indices_hash = ""
_last_quote_hash: dict[str, str] = {}


async def push_realtime_data(fetcher: SmartDataFetcher):
    """WebSocket实时数据推送，带去重机制"""
    global _last_indices_hash, _last_quote_hash

    while True:
        try:
            if not _manager.connections:
                await asyncio.sleep(5)
                continue

            if not _is_trading_hours():
                await asyncio.sleep(30)
                continue

            indices_data = {}
            try:
                overview = await fetcher.get_market_overview()
                cn = overview.get("cn_indices", {})
                hk = overview.get("hk_indices", {})
                us = overview.get("us_indices", {})
                indices_data = {**cn, **hk, **us}
            except Exception:
                pass

            indices_hash = json.dumps(indices_data, sort_keys=True)[:64]
            should_push_indices = indices_hash != _last_indices_hash
            if should_push_indices:
                _last_indices_hash = indices_hash

            subscribed = _manager.get_all_subscribed_symbols()
            quotes_data = {}
            for symbol in list(subscribed)[:30]:
                try:
                    rt = await fetcher.get_realtime(symbol)
                    if rt:
                        price_str = f"{rt.get('price', 0)}_{rt.get('change_pct', 0)}"
                        last_hash = _last_quote_hash.get(symbol, "")
                        if price_str != last_hash:
                            quotes_data[symbol] = rt
                            _last_quote_hash[symbol] = price_str
                except Exception:
                    pass

            if should_push_indices or quotes_data:
                message = {}
                if should_push_indices:
                    message["indices"] = indices_data
                if quotes_data:
                    message["quotes"] = quotes_data
                message["timestamp"] = time.time()

                msg_str = json.dumps(message, ensure_ascii=False)
                disconnected = []
                for ws in _manager.connections:
                    try:
                        await ws.send_text(msg_str)
                    except Exception:
                        disconnected.append(ws)
                for ws in disconnected:
                    _manager.disconnect(ws)

            await asyncio.sleep(5)
        except Exception as e:
            logger.debug(f"Push realtime error: {e}")
            await asyncio.sleep(10)
