import asyncio
import logging
import time
from datetime import datetime

import numpy as np
import pandas as pd
from fastapi import APIRouter, Path, Query, Request

from api.dependencies import FetcherDep
from api.routers.models import AlphaEvolveRequest, AuditStrategyRequest
from api.utils import json_response as _json_response
from api.utils import period_to_history as _period_to_history
from api.utils import safe_error, validate_symbol
from core.data_fetcher import get_fetcher
from core.database import get_db
from core.strategies import STRATEGY_REGISTRY

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/strategy/performance")
async def get_strategy_performance(
    fetcher: FetcherDep,
    symbol: str = Query(..., max_length=20, description="股票代码"),
    period: int = Query(120, description="回测天数", ge=30, le=500),
):
    try:
        from core.backtest import run_parallel_backtest
        from core.strategies import CompositeStrategy

        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 50:
            return _json_response(False, error="数据不足")

        df = df.tail(period + 60)
        if len(df) < 50:
            return _json_response(False, error="数据不足")

        composite = CompositeStrategy()
        strategy_specs = [
            {"name": s.name, "class_name": type(s).__name__}
            for s in composite.strategies
        ]

        parallel_results = await asyncio.to_thread(
            run_parallel_backtest, strategy_specs, df, symbol, 1000000
        )

        strategy_results = []
        for r in parallel_results:
            if "error" in r:
                strategy_results.append({
                    "name": r["strategy"],
                    "total_return": 0.0, "sharpe_ratio": 0.0, "max_drawdown": 0.0,
                    "win_rate": 0.0, "avg_pnl": 0.0, "total_trades": 0, "profit_factor": 0.0,
                })
            else:
                strategy_results.append({
                    "name": r["strategy"],
                    "total_return": r["total_return"],
                    "sharpe_ratio": r["sharpe_ratio"],
                    "max_drawdown": r["max_drawdown"],
                    "win_rate": r["win_rate"],
                    "avg_pnl": 0.0,
                    "total_trades": r["total_trades"],
                    "profit_factor": 0.0,
                })

        strategy_results.sort(key=lambda x: x["total_return"], reverse=True)
        best = strategy_results[0] if strategy_results else None
        return _json_response(True, data={
            "symbol": symbol,
            "period": period,
            "strategies": strategy_results,
            "best_strategy": best,
            "timestamp": time.time(),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/strategy/rolling-metrics")
async def get_rolling_strategy_metrics(
    fetcher: FetcherDep,
    symbol: str = Query(..., max_length=20, description="股票代码"),
    strategy_name: str = Query("adaptive", max_length=30, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$"),
    period: str = Query("1y", max_length=5),
    window: int = Query(60, ge=20, le=252),
):
    """滚动策略绩效指标（Sharpe/Sortino/Calmar/IR）"""
    try:
        if not validate_symbol(symbol):
            return _json_response(False, error="Invalid symbol")
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df is None or len(df) < 80:
            return _json_response(False, error="数据不足，至少需要80个交易日")
        from core.backtest import run_backtest
        bt_result = await asyncio.to_thread(
            run_backtest, symbol, strategy_name, "2020-01-01", "2025-12-31", 1000000, None, df
        )
        if bt_result is None or "error" in bt_result:
            return _json_response(False, error=bt_result.get("error", "回测失败") if bt_result else "回测失败")
        equity_data = bt_result.get("equity_curve", [])
        if len(equity_data) < 30:
            return _json_response(False, error="权益曲线数据不足")
        equity_values = [e["value"] for e in equity_data]
        equity_series = pd.Series(equity_values)
        returns = equity_series.pct_change().dropna()
        from core.rolling_metrics import get_rolling_metrics_tracker
        tracker = get_rolling_metrics_tracker()
        result = tracker.compute_all_rolling_metrics(returns, equity_curve=equity_series)
        result["symbol"] = symbol
        result["strategy"] = strategy_name
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/alpha/list")
async def list_alpha_factors(request: Request):
    try:
        from core.alpha_engine import AlphaGenerator
        gen = AlphaGenerator()
        alphas = gen.list_alphas()
        result = []
        for a in alphas:
            result.append({
                "name": a.name,
                "expression": a.expression,
                "category": a.category,
                "description": a.description,
            })
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/alpha/compute/{symbol}")
async def compute_alpha_factors(
    fetcher: FetcherDep,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
):
    try:
        from core.alpha_engine import AlphaGenerator
        from core.alpha_screener import AlphaScreener, AlphaScreeningConfig
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="数据不足")

        gen = AlphaGenerator()
        alpha_values = gen.compute_all_alphas(df)

        screener = AlphaScreener(AlphaScreeningConfig(ic_threshold=0.01, ic_ir_threshold=0.1))
        screened = screener.screen_all(alpha_values, df["close"])

        result = []
        for name, r in screened.items():
            result.append({
                "name": name,
                "ic": r.ic,
                "ic_ir": r.ic_ir,
                "turnover": r.turnover,
                "decay": r.decay,
                "passed": r.passed,
                "category": r.category,
            })
        result.sort(key=lambda x: abs(x["ic_ir"]), reverse=True)
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/regime/detect/{symbol}")
async def detect_market_regime(
    fetcher: FetcherDep,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
):
    try:
        from core.regime_detector import RegimeDetector
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足")

        detector = RegimeDetector()
        result = detector.detect(df)
        summary = detector.get_regime_summary(result)
        return _json_response(True, data=summary)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/risk/monitor/{symbol}")
async def get_risk_monitor(
    fetcher: FetcherDep,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
):
    try:
        from core.risk_monitor import EnhancedRiskMonitor
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足")

        monitor = EnhancedRiskMonitor()
        close = df["close"].astype(float)
        for price in close:
            monitor.update_equity(float(price))

        returns = close.pct_change().dropna()
        metrics = monitor.get_risk_metrics(returns=returns)
        should_liquidate, liq_reason = monitor.should_force_liquidate(metrics)
        should_reduce, reduce_scale, reduce_reason = monitor.should_reduce_position(metrics)

        return _json_response(True, data={
            "risk_level": metrics.risk_level.value,
            "volatility": metrics.volatility,
            "max_drawdown": metrics.max_drawdown,
            "current_drawdown": metrics.current_drawdown,
            "var_95": metrics.var_95,
            "cvar_95": metrics.cvar_95,
            "sharpe_ratio": metrics.sharpe_ratio,
            "sortino_ratio": metrics.sortino_ratio,
            "warnings": metrics.warnings,
            "should_force_liquidate": should_liquidate,
            "should_reduce_position": should_reduce,
            "reduce_scale": reduce_scale,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/metrics/institutional/{symbol}")
async def get_institutional_metrics(
    fetcher: FetcherDep,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    benchmark: str = Query("sh000300", max_length=20),
    period: str = Query("1y", max_length=5),
):
    try:
        from core.metrics import calc_all_metrics, metrics_to_dict
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足")

        close = df["close"].astype(float)
        equity_curve = list(close / close.iloc[0] * 100000)
        returns = close.pct_change().dropna()

        benchmark_returns = None
        try:
            bench_df = await fetcher.get_history(benchmark, _period_to_history(period), "daily", "qfq")
            if not bench_df.empty:
                benchmark_returns = bench_df["close"].astype(float).pct_change().dropna()
        except Exception as e:
            logger.debug("Benchmark fetch failed: %s", e)

        metrics = calc_all_metrics(equity_curve, returns, benchmark_returns)
        return _json_response(True, data=metrics_to_dict(metrics))
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/alpha/evolve")
async def run_alpha_evolution(
    fetcher: FetcherDep,
    body: AlphaEvolveRequest,
):
    try:
        from core.self_evolver import EvolutionConfig, SelfEvolver
        df = await fetcher.get_history(body.symbol, _period_to_history(body.period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="数据不足")

        config = EvolutionConfig(max_iterations=body.max_iterations)
        evolver = SelfEvolver(config=config)
        result = await asyncio.to_thread(evolver.evolve, df)
        report = evolver.get_evolution_report(result)
        return _json_response(True, data=report)
    except Exception as e:
        logger.error("Alpha evolution error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/audit/strategy")
async def audit_strategy(
    fetcher: FetcherDep,
    body: AuditStrategyRequest,
):
    try:
        from core.auto_auditor import AutoAuditor
        from core.backtest import BacktestEngine
        df = await fetcher.get_history(body.symbol, _period_to_history(body.period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="数据不足")

        strategy_cls = STRATEGY_REGISTRY.get(body.strategy_name)
        if not strategy_cls:
            return _json_response(False, error=f"未知策略: {body.strategy_name}")

        strategy = strategy_cls()
        engine = BacktestEngine(initial_capital=1000000)
        await asyncio.to_thread(engine.run, strategy, df)

        n = len(df)
        train_end = int(n * 0.7)
        train_df = df.iloc[:train_end]
        test_df = df.iloc[train_end:]

        train_result = engine.run(strategy, train_df)
        test_result = engine.run(strategy, test_df)

        from core.walk_forward import calc_strategy_metrics
        train_metrics = calc_strategy_metrics(train_result.equity_curve)
        test_metrics = calc_strategy_metrics(test_result.equity_curve)

        returns = df["close"].astype(float).pct_change().dropna()
        auditor = AutoAuditor()
        audit_report = auditor.audit(train_metrics, test_metrics, returns)

        return _json_response(True, data={
            "passed": audit_report.passed,
            "overall_score": audit_report.overall_score,
            "overfitting": {
                "is_overfitted": audit_report.overfitting.is_overfitted,
                "score": audit_report.overfitting.overfitting_score,
                "sharpe_gap": audit_report.overfitting.train_test_sharpe_gap,
            },
            "return_anomaly": {
                "has_anomaly": audit_report.return_anomaly.has_anomaly,
                "score": audit_report.return_anomaly.anomaly_score,
                "types": audit_report.return_anomaly.anomaly_types,
            },
            "recommendations": audit_report.recommendations,
        })
    except Exception as e:
        logger.error("Audit error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/strategies/list")
async def list_strategies():
    try:
        seen_classes = {}
        for name, cls in STRATEGY_REGISTRY.items():
            base_name = cls.__name__
            if base_name in seen_classes:
                continue
            seen_classes[base_name] = {
                "name": base_name,
                "aliases": [name],
            }
        for name, cls in STRATEGY_REGISTRY.items():
            base_name = cls.__name__
            if name not in seen_classes[base_name]["aliases"]:
                seen_classes[base_name]["aliases"].append(name)

        strategies = []
        strategy_descriptions = {
            "DualMAStrategy": "双均线交叉策略，快速均线上穿慢速均线买入",
            "MACDStrategy": "MACD金叉死叉策略，DIF上穿DEA买入",
            "KDJStrategy": "KDJ超买超卖策略，J线下穿低频买入",
            "BollingerBreakoutStrategy": "布林带突破策略，价格突破上轨做多",
            "MomentumStrategy": "动量策略，多周期动量确认",
            "MultiFactorConfluenceStrategy": "多因子共振策略，量化因子打分",
            "AdaptiveTrendFollowingStrategy": "自适应趋势策略，动态调整均线参数",
            "MeanReversionProStrategy": "均值回归策略，RSI+布林带+成交量确认",
            "VolatilitySqueezeBreakoutStrategy": "波动率压缩突破，BB宽度+ATR综合",
            "PatternTradingStrategy": "形态交易策略，识别经典K线形态",
            "OrderFlowOBVStrategy": "订单流OBV策略，成交量验证价格",
            "PriceVolumeTrend": "价量趋势策略，价量背离检测",
        }

        for base_name, info in sorted(seen_classes.items()):
            strategies.append({
                "name": base_name,
                "aliases": info["aliases"],
                "description": strategy_descriptions.get(base_name, "自定义策略"),
            })

        return _json_response(True, data={
            "total": len(strategies),
            "strategies": strategies,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/strategies/plugin-health")
async def plugin_health():
    try:
        from core.plugin_manager import PluginManager
        pm = PluginManager.get_instance()
        pm.register_from_registry(STRATEGY_REGISTRY)
        health = pm.get_health_report()
        return _json_response(True, data={
            "total": health.total_plugins,
            "healthy": health.healthy,
            "degraded": health.degraded,
            "failed": health.failed,
            "plugins": health.plugins,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error("Plugin health check failed: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/strategies/reload/{strategy_name}")
async def reload_strategy(strategy_name: str):
    try:
        from core.plugin_manager import PluginManager
        pm = PluginManager.get_instance()
        success = pm.reload_plugin(strategy_name)
        if success:
            return _json_response(True, data={"reloaded": strategy_name})
        return _json_response(False, error=f"Strategy '{strategy_name}' not reloadable or not found")
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/strategies/ranking")
async def strategy_ranking(
    symbol: str = Query("600519", max_length=10),
    period: str = Query("6mo", max_length=5),
):
    try:
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY
        get_db()
        fetcher = get_fetcher()
        kline = await fetcher.get_history(symbol, period=period)
        if kline is None or kline.empty:
            return _json_response(False, error="No kline data available")

        seen_classes = {}
        for _name, cls in STRATEGY_REGISTRY.items():
            base_name = cls.__name__
            if base_name not in seen_classes:
                seen_classes[base_name] = cls

        results = []
        for base_name, cls in seen_classes.items():
            try:
                strategy = cls()
                engine = BacktestEngine()
                result = engine.run(strategy, kline)
                if result:
                    sd = result.summary_dict()
                    sd["strategy"] = base_name
                    sd["trade_count"] = sd.pop("total_trades", 0)
                    results.append(sd)
            except Exception as e:
                logger.debug("策略排名-跳过股票 %s: %s", symbol, e)
                continue

        results.sort(key=lambda x: x.get("sharpe_ratio", float("-inf")), reverse=True)
        for i, r in enumerate(results):
            r["rank"] = i + 1

        return _json_response(True, data={
            "symbol": symbol,
            "period": period,
            "ranking": results[:15],
            "evaluated": len(results),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/fusion/methods")
async def fusion_methods():
    methods = [
        {"id": "ic_vol", "name": "IC-波动率加权", "description": "按IC绝对值/信号波动率分配权重，兼顾预测力和稳定性"},
        {"id": "equal", "name": "等权融合", "description": "所有策略等权重，简单稳健"},
        {"id": "ic", "name": "IC加权", "description": "按IC绝对值分配权重，偏向预测力强的因子"},
        {"id": "sharpe", "name": "Sharpe加权", "description": "按历史Sharpe比率分配权重"},
        {"id": "rank", "name": "Rank加权", "description": "按IC排名分配权重，减少极端值影响"},
    ]
    return _json_response(True, data={"methods": methods})


@router.post("/fusion/signal")
async def fusion_signal(
    request: Request,
    symbol: str = Query(..., max_length=10),
    method: str = Query("ic_vol", max_length=10),
    min_ic: float = Query(0.02, ge=0),
    max_strategies: int = Query(10, ge=1, le=20),
    period: str = Query("6mo", max_length=5),
):
    try:
        from core.alpha_engine import AlphaEngine
        from core.strategy_fusion import FusionConfig, StrategyFusion
        fetcher = get_fetcher()
        kline = await fetcher.get_history(symbol, period=period)
        if kline is None or kline.empty:
            return _json_response(False, error="No kline data available")

        alpha_engine = AlphaEngine()
        alpha_results = alpha_engine.compute_all(kline)

        config = FusionConfig(
            method=method, min_ic=min_ic, max_strategies=max_strategies,
        )
        fusion = StrategyFusion(config)
        result = fusion.fuse(alpha_results, method=method)

        signal_stats = {}
        if len(result.combined_signal) > 0:
            cs = result.combined_signal
            signal_stats = {
                "mean": round(float(cs.mean()), 6),
                "std": round(float(cs.std()), 6),
                "min": round(float(cs.min()), 6),
                "max": round(float(cs.max()), 6),
                "latest": round(float(cs.iloc[-1]), 6),
            }

        return _json_response(True, data={
            "symbol": symbol,
            "method": result.method,
            "n_strategies": result.n_strategies,
            "weights": result.strategy_weights,
            "contribution": result.contribution,
            "signal_stats": signal_stats,
            "latest_signal": "bullish" if signal_stats.get("latest", 0) > 0.5 else (
                "bearish" if signal_stats.get("latest", 0) < -0.5 else "neutral"
            ),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/execution/methods")
async def execution_methods():
    methods = [
        {"id": "market", "name": "市价单", "description": "立即以当前价格成交，含滑点模拟"},
        {"id": "twap", "name": "TWAP时间加权", "description": "将订单均匀分拆到N个时间bar执行"},
        {"id": "vwap", "name": "VWAP成交量加权", "description": "按历史成交量分布分拆订单执行"},
    ]
    return _json_response(True, data={"methods": methods})


@router.post("/execution/simulate")
async def execution_simulate(
    fetcher: FetcherDep,
    symbol: str = Query(..., max_length=10),
    side: str = Query("buy", max_length=4),
    quantity: int = Query(..., gt=0),
    method: str = Query("market", max_length=10),
    n_bars: int = Query(6, ge=1, le=20),
):
    try:
        from core.execution_engine import ExecutionEngine
        if side not in ("buy", "sell"):
            return _json_response(False, error="side must be 'buy' or 'sell'")
        if method not in ("market", "twap", "vwap"):
            return _json_response(False, error="method must be 'market', 'twap', or 'vwap'")

        rt = await fetcher.get_realtime(symbol)
        if not rt or rt.get("price", 0) <= 0:
            return _json_response(False, error="No realtime price available")

        current_price = float(rt["price"])
        engine = ExecutionEngine()

        if method == "market":
            result = engine.execute_market_order(side, quantity, current_price)
        elif method == "twap":
            kline = await fetcher.get_history(symbol, period="1mo")
            if kline is None or kline.empty:
                return _json_response(False, error="No history data for TWAP")
            result = engine.execute_twap_order(side, quantity, kline, n_bars=n_bars)
        else:
            kline = await fetcher.get_history(symbol, period="1mo")
            if kline is None or kline.empty:
                return _json_response(False, error="No history data for VWAP")
            result = engine.execute_vwap_order(side, quantity, kline, n_bars=n_bars)

        return _json_response(True, data={
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "method": result.execution_method,
            "filled_quantity": result.filled_quantity,
            "avg_fill_price": round(result.avg_fill_price, 4),
            "total_cost": round(result.total_cost, 2),
            "slippage": round(result.slippage, 2),
            "commission": round(result.commission, 2),
            "stamp_tax": round(result.stamp_tax, 2),
            "cost_bps": round(result.total_cost / (current_price * quantity) * 10000, 2) if quantity > 0 else 0,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/alpha/screen")
async def alpha_screen(
    request: Request,
    symbol: str = Query(..., max_length=10),
    ic_threshold: float = Query(0.02, ge=0),
    ic_ir_threshold: float = Query(0.3, ge=0),
    period: str = Query("1y", max_length=5),
):
    try:
        from core.alpha_engine import AlphaEngine
        from core.alpha_screener import AlphaScreener
        fetcher = get_fetcher()
        kline = await fetcher.get_history(symbol, period=period)
        if kline is None or kline.empty:
            return _json_response(False, error="No kline data available")

        alpha_engine = AlphaEngine()
        alpha_results = alpha_engine.compute_all(kline)

        screener = AlphaScreener()
        screener.screen(
            alpha_results,
            ic_threshold=ic_threshold,
            ic_ir_threshold=ic_ir_threshold,
        )

        screened = []
        for name, result in alpha_results.items():
            screened.append({
                "name": name,
                "ic": round(result.ic, 6),
                "ic_ir": round(result.ic_ir, 6),
                "turnover": round(result.turnover, 4) if hasattr(result, "turnover") else None,
                "pass": abs(result.ic) >= ic_threshold and abs(result.ic_ir) >= ic_ir_threshold,
            })
        screened.sort(key=lambda x: abs(x.get("ic_ir", 0)), reverse=True)

        passed = [s for s in screened if s["pass"]]
        return _json_response(True, data={
            "symbol": symbol,
            "total_factors": len(screened),
            "passed": len(passed),
            "pass_rate": round(len(passed) / len(screened) * 100, 1) if screened else 0,
            "factors": screened[:20],
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/strategy/param-specs")
async def get_strategy_param_specs():
    try:
        from core.param_optimizer import get_param_specs
        specs = get_param_specs()
        return _json_response(True, data={"strategies": specs})
    except Exception as e:
        logger.error("Param specs error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/strategy/optimize-params")
async def optimize_strategy_params(
    fetcher: FetcherDep,
    strategy_name: str = Query(..., max_length=50),
    symbol: str = Query(..., max_length=20),
    metric: str = Query("sharpe_ratio", max_length=20),
    period: str = Query("1y", max_length=5),
    max_combos: int = Query(200, ge=10, le=500),
):
    try:
        if not validate_symbol(symbol):
            return _json_response(False, error="Invalid symbol")
        if metric not in ("sharpe_ratio", "total_return", "annual_return", "max_drawdown", "win_rate"):
            return _json_response(False, error="Invalid metric")

        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="Insufficient data (need at least 60 bars)")

        from core.param_optimizer import run_param_optimization
        result = run_param_optimization(
            strategy_name=strategy_name,
            df=df,
            metric=metric,
            max_combos=max_combos,
            timeout_seconds=30.0,
        )
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Param optimization error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/strategy/bayesian-optimize")
async def bayesian_optimize_strategy(
    fetcher: FetcherDep,
    strategy_name: str = Query(..., max_length=50),
    symbol: str = Query(..., max_length=20),
    metric: str = Query("sharpe_ratio", max_length=20),
    period: str = Query("1y", max_length=5),
    n_trials: int = Query(30, ge=10, le=100),
):
    """使用差分进化算法进行智能参数优化"""
    try:
        if not validate_symbol(symbol):
            return _json_response(False, error="Invalid symbol")
        if metric not in ("sharpe_ratio", "total_return", "annual_return", "max_drawdown", "win_rate"):
            return _json_response(False, error="Invalid metric")

        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="Insufficient data (need at least 60 bars)")

        from core.param_optimizer import run_bayesian_optimization
        result = await asyncio.to_thread(
            run_bayesian_optimization,
            strategy_name=strategy_name,
            df=df,
            metric=metric,
            n_trials=n_trials,
            timeout_seconds=45.0,
        )
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Bayesian optimization error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/single-stock/stress-test")
async def run_single_stock_stress_test(
    fetcher: FetcherDep,
    symbol: str = Query(..., max_length=20),
    period: str = Query("1y", max_length=5),
    scenarios: str = Query("", max_length=200),
):
    try:
        if not validate_symbol(symbol):
            return _json_response(False, error="Invalid symbol")

        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error="Insufficient data")

        from core.param_optimizer import run_stress_test
        scenario_list = [s.strip() for s in scenarios.split(",") if s.strip()] if scenarios else None
        result = run_stress_test(df, scenarios=scenario_list)
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Stress test error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/volatility/garch/{symbol}")
async def garch_volatility_forecast(
    fetcher: FetcherDep,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
):
    try:
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="Insufficient data (need 60+ bars)")

        from core.volatility import fit_garch
        returns = df["close"].astype(float).pct_change().dropna().values
        returns = np.clip(returns, -0.15, 0.15)
        result = fit_garch(returns)
        result["symbol"] = symbol
        result["period"] = period
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("GARCH forecast error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/regime/hmm/{symbol}")
async def hmm_regime_detection(
    fetcher: FetcherDep,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
    n_states: int = Query(3, ge=2, le=5),
):
    try:
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="Insufficient data (need 60+ bars)")

        from core.volatility import detect_regime_hmm
        returns = df["close"].astype(float).pct_change().dropna().values
        result = detect_regime_hmm(returns, n_states=n_states)
        result["symbol"] = symbol
        result["period"] = period
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("HMM regime detection error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/strategy/performance_heatmap")
async def get_strategy_performance_heatmap(
    fetcher: FetcherDep,
    symbols: str = Query(..., max_length=300, description="逗号分隔的股票代码，最多10个"),
    period: int = Query(120, description="回测天数", ge=30, le=500),
):
    """策略性能热力图：多股票×多策略的Sharpe比率矩阵"""
    try:
        from core.backtest import run_parallel_backtest
        from core.strategies import CompositeStrategy

        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()][:10]
        if not symbol_list:
            return _json_response(False, error="请提供股票代码")

        composite = CompositeStrategy()
        strategy_names = [s.name for s in composite.strategies]

        heatmap_data = []
        strategy_stats = {name: {"sharpe_sum": 0.0, "count": 0} for name in strategy_names}

        history_tasks = [fetcher.get_history(sym, period="all", kline_type="daily", adjust="qfq") for sym in symbol_list]
        history_results = await asyncio.gather(*history_tasks, return_exceptions=True)

        for idx, symbol in enumerate(symbol_list):
            try:
                df = history_results[idx]
                if isinstance(df, Exception):
                    continue
                if df is None or len(df) < 50:
                    continue
                df = df.tail(period + 60)
                if len(df) < 50:
                    continue

                strategy_specs = [{"name": s.name, "class_name": type(s).__name__} for s in composite.strategies]
                parallel_results = await asyncio.to_thread(
                    run_parallel_backtest, strategy_specs, df, symbol, 1000000
                )

                row = {"symbol": symbol}
                for r in parallel_results:
                    name = r.get("strategy", "unknown")
                    sharpe = r.get("sharpe_ratio", 0.0) if "error" not in r else 0.0
                    row[name] = round(sharpe, 3)
                    if name in strategy_stats:
                        strategy_stats[name]["sharpe_sum"] += sharpe
                        strategy_stats[name]["count"] += 1
                heatmap_data.append(row)
            except Exception as e:
                logger.debug("Heatmap symbol %s failed: %s", symbol, e)
                continue

        strategy_ranking = [
            {"name": name, "avg_sharpe": round(stats["sharpe_sum"] / max(stats["count"], 1), 3)}
            for name, stats in strategy_stats.items()
        ]
        strategy_ranking.sort(key=lambda x: x["avg_sharpe"], reverse=True)

        return _json_response(True, data={
            "heatmap": heatmap_data,
            "strategies": strategy_names,
            "strategy_ranking": strategy_ranking,
            "period": period,
            "timestamp": time.time(),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/strategy/compare")
async def compare_strategies(
    fetcher: FetcherDep,
    symbols: str = Query(..., max_length=300, description="逗号分隔的股票代码"),
    strategies: str = Query(..., max_length=300, description="逗号分隔的策略名称"),
    period: str = Query("6m", max_length=5, description="回测周期"),
    capital: float = Query(100000, ge=10000, le=10000000, description="初始资金"),
):
    """多策略性能对比：同标的、同周期下并排比较多个策略的回测结果"""
    try:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        strategy_names = [s.strip() for s in strategies.split(",") if s.strip()]
        if not symbol_list or not strategy_names:
            return _json_response(False, error="需要至少1个股票和1个策略")
        if len(strategy_names) > 6:
            return _json_response(False, error="最多同时比较6个策略")

        from core.backtest import BacktestEngine
        from core.strategies import get_strategy_registry

        registry = get_strategy_registry()
        results: list[dict] = []
        metrics_keys = [
            "total_return", "annual_return", "sharpe_ratio", "max_drawdown",
            "win_rate", "profit_factor", "total_trades", "sortino_ratio",
            "calmar_ratio", "omega_ratio",
        ]
        comparison_matrix: dict[str, dict[str, float | int]] = {}

        history_map = await fetcher.get_history_batch(
            symbol_list[:5], _period_to_history(period), "daily", "qfq"
        )

        for strat_name in strategy_names:
            cls = registry.get(strat_name)
            if cls is None:
                results.append({"strategy": strat_name, "error": f"未知策略: {strat_name}"})
                continue

            all_summaries = []
            for sym, df in history_map.items():
                try:
                    if len(df) < 30:
                        continue
                    bt = BacktestEngine(initial_capital=capital)
                    r = bt.run(cls(), df, symbol=sym)
                    all_summaries.append(r.summary_dict())
                except Exception as e:
                    logger.debug("Compare backtest failed: %s/%s: %s", strat_name, sym, e)
                    continue

            if not all_summaries:
                results.append({"strategy": strat_name, "error": "无有效回测数据"})
                continue

            avg_metrics: dict[str, float] = {}
            for key in metrics_keys:
                vals = [s.get(key, 0) for s in all_summaries if isinstance(s.get(key), (int, float))]
                avg_metrics[key] = round(sum(vals) / len(vals), 4) if vals else 0.0
            comparison_matrix[strat_name] = avg_metrics

            best = max(all_summaries, key=lambda s: s.get("sharpe_ratio", -999))
            worst = min(all_summaries, key=lambda s: s.get("sharpe_ratio", -999))

            results.append({
                "strategy": strat_name,
                "n_symbols_tested": len(all_summaries),
                "average": avg_metrics,
                "best_symbol": {
                    "strategy_name": best.get("strategy_name", ""),
                    "sharpe_ratio": best.get("sharpe_ratio", 0),
                    "total_return": best.get("total_return", 0),
                    "max_drawdown": best.get("max_drawdown", 0),
                },
                "worst_symbol": {
                    "strategy_name": worst.get("strategy_name", ""),
                    "sharpe_ratio": worst.get("sharpe_ratio", 0),
                    "total_return": worst.get("total_return", 0),
                    "max_drawdown": worst.get("max_drawdown", 0),
                },
            })

        ranking = sorted(
            comparison_matrix.items(),
            key=lambda x: x[1].get("sharpe_ratio", -999),
            reverse=True,
        )

        return _json_response(True, data={
            "strategies": results,
            "ranking": [
                {"strategy": name, "avg_sharpe": metrics.get("sharpe_ratio", 0)}
                for name, metrics in ranking
            ],
            "comparison_matrix": comparison_matrix,
            "period": period,
            "symbols": symbol_list[:5],
            "timestamp": time.time(),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/strategy/dashboard")
async def get_strategy_dashboard(
    fetcher: FetcherDep,
    symbol: str = Query(..., description="股票代码"),
    period: int = Query(120, description="回测天数", ge=30, le=500),
):
    """综合策略性能仪表盘：回测结果 + IC监控 + 市场状态权重 + 风险平价"""
    try:
        from core.backtest import run_parallel_backtest
        from core.factor_validity import FactorValidityMonitor
        from core.regime_weight_tracker import RegimeWeightTracker
        from core.risk_parity_portfolio import RiskParityPortfolio
        from core.strategies import CompositeStrategy

        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 50:
            return _json_response(False, error="数据不足")

        df = df.tail(period + 60)
        if len(df) < 50:
            return _json_response(False, error="数据不足")

        composite = CompositeStrategy()
        strategy_specs = [
            {"name": s.name, "class_name": type(s).__name__}
            for s in composite.strategies
        ]
        strategy_names = [s["name"] for s in strategy_specs]

        parallel_results = await asyncio.to_thread(
            run_parallel_backtest, strategy_specs, df, symbol, 1000000
        )

        strategy_results = []
        for r in parallel_results:
            if "error" in r:
                strategy_results.append({
                    "name": r["strategy"],
                    "total_return": 0.0, "sharpe_ratio": 0.0, "max_drawdown": 0.0,
                    "win_rate": 0.0, "total_trades": 0,
                })
            else:
                strategy_results.append({
                    "name": r["strategy"],
                    "total_return": r.get("total_return", 0.0),
                    "sharpe_ratio": r.get("sharpe_ratio", 0.0),
                    "max_drawdown": r.get("max_drawdown", 0.0),
                    "win_rate": r.get("win_rate", 0.0),
                    "total_trades": r.get("total_trades", 0),
                })

        strategy_results.sort(key=lambda x: x["total_return"], reverse=True)

        regime_tracker = RegimeWeightTracker(strategy_names=strategy_names)
        regime_snap = regime_tracker.update(df)
        regime_data = {
            "current_regime": regime_snap.regime,
            "confidence": regime_snap.regime_confidence,
            "strategy_weights": regime_snap.strategy_weights,
            "indicators": regime_snap.indicators,
        }

        ic_data = {}
        factor_monitor = FactorValidityMonitor(lookback=60, ic_threshold=0.03)
        for sr in strategy_results[:5]:
            name = sr["name"]
            ic_data[name] = {
                "ic_mean": factor_monitor.get_ic_mean(name),
                "ic_ir": factor_monitor.get_ic_ir(name),
                "is_valid": factor_monitor.is_valid(name),
                "weight_adjustment": factor_monitor.get_weight_adjustment(name),
            }

        risk_data = {}
        try:
            if len(strategy_names) >= 2:
                portfolio = RiskParityPortfolio(symbols=strategy_names[:5])
                returns_map = {}
                for r in parallel_results:
                    name = r.get("strategy", "")
                    dr = r.get("daily_returns", [])
                    if dr:
                        returns_map[name] = dr
                if returns_map:
                    min_len = min(len(v) for v in returns_map.values())
                    for i in range(min(30, min_len)):
                        ret_vec = []
                        for sn in strategy_names[:5]:
                            vals = returns_map.get(sn, [])
                            ret_vec.append(vals[i] if i < len(vals) else 0.0)
                        while len(ret_vec) < min(5, len(strategy_names)):
                            ret_vec.append(0.0)
                        portfolio.update_returns(np.array(ret_vec[:5]))
                    state = portfolio.compute_target_weights()
                    risk_data = {
                        "weights": state.weights,
                        "risk_contributions": state.risk_contributions,
                        "portfolio_volatility": state.portfolio_volatility,
                        "ic_adjustments": state.ic_adjustments,
                    }
        except Exception as e:
            logger.debug("Risk parity computation skipped: %s", e)

        return _json_response(True, data={
            "symbol": symbol,
            "period": period,
            "strategies": strategy_results,
            "best_strategy": strategy_results[0] if strategy_results else None,
            "regime": regime_data,
            "factor_validity": ic_data,
            "risk_parity": risk_data,
            "timestamp": time.time(),
        })
    except Exception as e:
        logger.error("Strategy dashboard error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/strategy/lifecycle/list")
async def list_strategy_lifecycle():
    """列出所有策略的生命周期状态"""
    try:
        db = get_db()
        rows = db.fetchall("SELECT version_id, strategy_name, version, state, created_at FROM strategy_versions ORDER BY created_at DESC")
        return _json_response(True, data={
            "strategies": [
                {
                    "version_id": row["version_id"],
                    "name": row["strategy_name"],
                    "version": row["version"],
                    "state": row["state"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ],
            "total": len(rows),
        })
    except Exception as e:
        logger.error("List lifecycle error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/strategy/lifecycle/register")
async def register_strategy_lifecycle(request: Request):
    """注册新策略到生命周期管理"""
    try:
        from core.strategy_lifecycle import StrategyConfig, StrategyLifecycleManager

        body = await request.json()
        name = body.get("name", "").strip()
        version = body.get("version", "1.0.0").strip()
        if not name:
            return _json_response(False, error="策略名称不能为空")

        config = StrategyConfig(
            name=name,
            version=version,
            parameters=body.get("parameters", {}),
            risk_limits=body.get("risk_limits", {}),
            universe=body.get("universe", {}),
            schedule=body.get("schedule", {}),
        )

        manager = StrategyLifecycleManager()
        version_id = manager.register_strategy(config)

        return _json_response(True, data={
            "version_id": version_id,
            "state": "research",
            "message": "策略已注册到生命周期管理",
        })
    except Exception as e:
        logger.error("Register lifecycle error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/strategy/lifecycle/promote")
async def promote_strategy_lifecycle(request: Request):
    """检查策略晋升资格并执行状态转换"""
    try:
        from core.strategy_lifecycle import StrategyLifecycleManager

        body = await request.json()
        version_id = body.get("version_id", "").strip()
        if not version_id:
            return _json_response(False, error="version_id不能为空")

        manager = StrategyLifecycleManager()

        result = manager.check_promotion_eligibility(version_id)
        if not result.approved:
            return _json_response(False, error=f"晋升不通过: {result.reason}", data={
                "from_state": result.from_state.value,
                "to_state": result.to_state.value,
                "metrics_snapshot": result.metrics_snapshot,
            })

        from core.strategy_lifecycle import StrategyState
        state_map = {
            "research": StrategyState.BACKTEST_PASSED,
            "backtest_passed": StrategyState.PAPER_TRADING,
            "paper_trading": StrategyState.PILOT,
            "pilot": StrategyState.LIVE,
        }
        new_state = state_map.get(result.from_state.value)
        if new_state is None:
            return _json_response(False, error="无法确定目标状态")

        success = manager.update_state(version_id, new_state)
        if not success:
            return _json_response(False, error="状态转换失败")

        return _json_response(True, data={
            "version_id": version_id,
            "from_state": result.from_state.value,
            "to_state": new_state.value,
            "message": f"策略已从 {result.from_state.value} 晋升到 {new_state.value}",
        })
    except Exception as e:
        logger.error("Promote lifecycle error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/strategy/lifecycle/update-metrics")
async def update_strategy_metrics(request: Request):
    """更新策略指标数据"""
    try:
        from core.strategy_lifecycle import StrategyLifecycleManager

        body = await request.json()
        version_id = body.get("version_id", "").strip()
        metrics = body.get("metrics", {})
        if not version_id:
            return _json_response(False, error="version_id不能为空")

        manager = StrategyLifecycleManager()
        manager.record_metrics(version_id, metrics)

        return _json_response(True, data={"version_id": version_id, "message": "指标已更新"})
    except Exception as e:
        logger.error("Update metrics error: %s", e)
        return _json_response(False, error=safe_error(e))
