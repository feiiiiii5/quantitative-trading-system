import logging
from typing import Optional

from fastapi import APIRouter, Query, Request

logger = logging.getLogger(__name__)
backtest_router = APIRouter()


def _json_response(success: bool, data=None, error: str = ""):
    return {"success": success, "data": data, "error": error}


@backtest_router.get("/backtest/strategies")
async def get_backtest_strategies(request: Request):
    try:
        info = request.app.state.composite_strategy.get_strategy_info()
        return _json_response(True, data=info)
    except Exception as e:
        return _json_response(False, error=str(e))


@backtest_router.post("/backtest/run")
async def run_backtest(
    request: Request,
    symbol: str = Query(...),
    strategy_type: str = Query("composite"),
    start_date: str = Query("2023-01-01"),
    end_date: str = Query("2024-12-31"),
    initial_capital: float = Query(1000000),
    commission: float = Query(0.0003),
):
    try:
        from core.data_fetcher import KLINE_TYPE_MAP
        kline_type = "daily"
        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, "1y", kline_type)
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足，至少需要30个交易日")

        engine = request.app.state.backtest_engine
        strategies = request.app.state.composite_strategy.strategies
        results = engine.run_multi(strategies, df)

        output = {}
        for name, result in results.items():
            output[name] = {
                "strategy_name": result.strategy_name,
                "total_return": result.total_return,
                "annual_return": result.annual_return,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
                "profit_factor": result.profit_factor,
                "total_trades": result.total_trades,
                "win_trades": result.win_trades,
                "loss_trades": result.loss_trades,
                "avg_profit": result.avg_profit,
                "avg_loss": result.avg_loss,
                "benchmark_return": result.benchmark_return,
                "alpha": result.alpha,
                "beta": result.beta,
                "equity_curve": result.equity_curve[-200:] if result.equity_curve else [],
                "drawdown_curve": result.drawdown_curve[-200:] if result.drawdown_curve else [],
                "dates": result.dates[-200:] if result.dates else [],
            }

        return _json_response(True, data=output)
    except Exception as e:
        logger.error(f"backtest run error: {e}", exc_info=True)
        return _json_response(False, error=str(e))


@backtest_router.get("/backtest/result/{task_id}")
async def get_backtest_result(request: Request, task_id: str):
    return _json_response(False, error="回测结果查询暂不支持")


@backtest_router.get("/backtest/compare")
async def compare_strategies(
    request: Request,
    symbol: str = Query(...),
    period: str = Query("1y"),
):
    try:
        from core.data_fetcher import KLINE_TYPE_MAP
        kline_type = KLINE_TYPE_MAP.get(period, "daily")
        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period, kline_type)
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足")

        engine = request.app.state.backtest_engine
        strategies = request.app.state.composite_strategy.strategies
        results = engine.run_multi(strategies, df)

        comparison = []
        for name, result in results.items():
            comparison.append({
                "strategy_name": result.strategy_name,
                "total_return": result.total_return,
                "annual_return": result.annual_return,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
                "profit_factor": result.profit_factor,
                "total_trades": result.total_trades,
            })

        comparison.sort(key=lambda x: x["total_return"], reverse=True)
        return _json_response(True, data=comparison)
    except Exception as e:
        logger.error(f"compare strategies error: {e}", exc_info=True)
        return _json_response(False, error=str(e))
