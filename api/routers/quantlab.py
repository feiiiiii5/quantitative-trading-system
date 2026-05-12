from __future__ import annotations

import asyncio
import logging
import time

import pandas as pd
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from api.utils import json_response as _json_response
from api.utils import safe_error
from api.routers.models import (
    AnalyzeBacktestRequest, AutoOptimizeRequest, CompareStrategiesRequest,
    DiagnoseRequest, SensitivityHeatmapRequest, SignalReplayRequest, WalkForwardRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class StrategyParseRequest(BaseModel):
    strategy_name: str = Field(..., min_length=1, max_length=100)
    strategy_version: str = Field("1.0.0", max_length=20)
    asset_class: str = Field("spot", pattern=r"^(spot|futures|options|forex|crypto)$")
    timeframe: str = Field("1d", pattern=r"^(tick|1m|5m|15m|1h|4h|1d)$")
    market_type: str = Field("trend", pattern=r"^(trend|mean_reversion|momentum|arbitrage|market_making|ml_driven)$")
    parameters: dict = Field(default_factory=dict)
    indicators: list[dict] = Field(default_factory=list)
    signal_logic: dict = Field(default_factory=dict)
    risk_management: dict = Field(default_factory=dict)
    execution_model: dict = Field(default_factory=dict)


@router.post("/quantlab/parse-strategy")
async def parse_strategy(request: Request, body: StrategyParseRequest):
    try:
        from core.strategy_schema import (
            AssetClass,
            Timeframe,
            MarketType,
            StrategyDefinition,
            StrategyMeta,
            ParameterSpec,
            IndicatorSpec,
            SignalLogic,
            RiskManagement,
            ExecutionModel,
        )
        meta = StrategyMeta(
            name=body.strategy_name,
            version=body.strategy_version,
            asset_class=AssetClass(body.asset_class),
            timeframe=Timeframe(body.timeframe),
            market_type=MarketType(body.market_type),
        )
        params = {k: ParameterSpec(**v) for k, v in body.parameters.items()} if body.parameters else {}
        indicators = [IndicatorSpec(**ind) for ind in body.indicators] if body.indicators else []
        signals = SignalLogic(**body.signal_logic) if body.signal_logic else SignalLogic()
        risk = RiskManagement(**body.risk_management) if body.risk_management else RiskManagement()
        execution = ExecutionModel(**body.execution_model) if body.execution_model else ExecutionModel()

        definition = StrategyDefinition(
            strategy_meta=meta,
            parameters=params,
            indicators=indicators,
            signal_logic=signals,
            risk_management=risk,
            execution_model=execution,
        )
        return _json_response(True, data={
            "summary_card": definition.summary_card(),
            "min_bars_required": definition.min_bars_required(),
            "definition": definition.model_dump(),
        })
    except Exception as e:
        logger.error("Strategy parse error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/quantlab/diagnose")
async def diagnose_strategy(request: Request, body: DiagnoseRequest):
    try:
        from core.backtest import BacktestEngine
        from core.backtest.enhanced_metrics import compute_comprehensive_metrics
        from core.strategy_schema import (
            AssetClass,
            Timeframe,
            MarketType,
            StrategyDefinition,
            StrategyMeta,
            ParameterSpec,
            IndicatorSpec,
            SignalLogic,
            RiskManagement,
            ExecutionModel,
        )
        from core.strategy_analyzer import analyze_backtest_result
        from core.strategies import STRATEGY_REGISTRY
        from core.data_fetcher import get_fetcher

        strategy_name = body.strategy
        symbol = body.symbol
        if strategy_name not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"策略{strategy_name}不存在")

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 60:
            return _json_response(False, error="数据不足")

        strategy_cls = STRATEGY_REGISTRY[strategy_name]
        strategy_instance = strategy_cls()
        n_params = len(strategy_instance.get_param_space()) if hasattr(strategy_instance, "get_param_space") else 0

        engine = BacktestEngine()
        result = await asyncio.to_thread(engine.run, strategy_instance, df, symbol)

        metrics = compute_comprehensive_metrics(
            equity_curve=result.equity_curve,
            dates=result.dates,
            trades=result.trades,
            initial_capital=1_000_000,
            n_params=n_params,
        )

        definition = StrategyDefinition(
            strategy_meta=StrategyMeta(
                name=strategy_name,
                market_type=MarketType.TREND,
            ),
        )
        analysis = analyze_backtest_result(definition, result.to_dict())

        quick_stats = {
            "total_return_pct": round(result.total_return, 2),
            "cagr_pct": round(result.annual_return, 2),
            "sharpe": round(result.sharpe_ratio, 2),
            "max_dd_pct": round(result.max_drawdown * 100, 2),
            "win_rate_pct": round(result.win_rate, 1),
        }

        return _json_response(True, data={
            "quick_stats": quick_stats,
            "comprehensive_metrics": {
                "returns": {k: v for k, v in metrics.returns.__dict__.items()},
                "risk": {k: v for k, v in metrics.risk.__dict__.items()},
                "risk_adjusted": {k: v for k, v in metrics.risk_adjusted.__dict__.items()},
                "trades": {k: v for k, v in metrics.trades.__dict__.items()},
                "distribution": {
                    "skewness": metrics.distribution.skewness,
                    "kurtosis": metrics.distribution.kurtosis,
                    "tail_ratio": metrics.distribution.tail_ratio,
                },
                "guardrail_warnings": metrics.guardrail_warnings,
            },
            "strategy_analysis": analysis,
            "disclaimer": "Past backtest results do not guarantee future performance. All metrics are subject to estimation error.",
        })
    except Exception as e:
        logger.error("Diagnose strategy error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/quantlab/analyze-strategy")
async def analyze_strategy_endpoint(request: Request, body: StrategyParseRequest):
    try:
        from core.strategy_schema import (
            AssetClass,
            Timeframe,
            MarketType,
            StrategyDefinition,
            StrategyMeta,
            ParameterSpec,
            IndicatorSpec,
            SignalLogic,
            RiskManagement,
            ExecutionModel,
        )
        from core.strategy_analyzer import analyze_strategy
        meta = StrategyMeta(
            name=body.strategy_name,
            version=body.strategy_version,
            asset_class=AssetClass(body.asset_class),
            timeframe=Timeframe(body.timeframe),
            market_type=MarketType(body.market_type),
        )
        params = {k: ParameterSpec(**v) for k, v in body.parameters.items()} if body.parameters else {}
        indicators = [IndicatorSpec(**v) for v in body.indicators] if body.indicators else []
        signals = SignalLogic(**body.signal_logic) if body.signal_logic else SignalLogic()
        risk = RiskManagement(**body.risk_management) if body.risk_management else RiskManagement()
        execution = ExecutionModel(**body.execution_model) if body.execution_model else ExecutionModel()
        definition = StrategyDefinition(
            strategy_meta=meta,
            parameters=params,
            indicators=indicators,
            signal_logic=signals,
            risk_management=risk,
            execution_model=execution,
        )
        analysis = analyze_strategy(definition)
        return _json_response(True, data={
            "edge_analysis": {
                "alpha_source": analysis.edge.alpha_source,
                "optimal_regime": analysis.edge.optimal_regime,
                "lookahead_bias_risks": analysis.edge.lookahead_bias_risks,
                "survivorship_bias_risks": analysis.edge.survivorship_bias_risks,
                "overfitting_risk": analysis.edge.overfitting_risk,
            },
            "indicator_dependencies": [
                {"name": d.name, "lookback": d.lookback, "min_bars_before_signal": d.min_bars_before_signal}
                for d in analysis.indicator_dependencies
            ],
            "regime_sensitivity": [
                {"regime": r.regime.value, "expected_sharpe": r.expected_sharpe,
                 "expected_return_pct": r.expected_return_pct, "expected_max_dd_pct": r.expected_max_dd_pct,
                 "confidence": r.confidence}
                for r in analysis.regime_sensitivity
            ],
            "weaknesses": [
                {"title": w.title, "description": w.description, "severity": w.severity, "mitigation": w.mitigation}
                for w in analysis.weaknesses
            ],
            "improvements": [
                {"title": i.title, "description": i.description, "expected_impact": i.expected_impact, "effort": i.implementation_effort}
                for i in analysis.improvements
            ],
        })
    except Exception as e:
        logger.error("Strategy analyze error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/quantlab/analyze-backtest")
async def analyze_backtest_endpoint(request: Request, body: AnalyzeBacktestRequest):
    try:
        from core.strategy_schema import (
            AssetClass,
            Timeframe,
            MarketType,
            StrategyDefinition,
            StrategyMeta,
            ParameterSpec,
            IndicatorSpec,
            SignalLogic,
            RiskManagement,
            ExecutionModel,
        )
        from core.strategy_analyzer import analyze_backtest_result

        strategy_data = body.strategy
        result_data = body.result
        meta = StrategyMeta(
            name=strategy_data.get("name", "unknown"),
            asset_class=AssetClass(strategy_data.get("asset_class", "spot")),
            timeframe=Timeframe(strategy_data.get("timeframe", "1d")),
            market_type=MarketType(strategy_data.get("market_type", "trend")),
        )
        params = {k: ParameterSpec(**v) for k, v in strategy_data.get("parameters", {}).items()}
        indicators = [IndicatorSpec(**v) for v in strategy_data.get("indicators", [])]
        definition = StrategyDefinition(
            strategy_meta=meta,
            parameters=params,
            indicators=indicators,
            signal_logic=SignalLogic(**strategy_data.get("signal_logic", {})),
            risk_management=RiskManagement(**strategy_data.get("risk_management", {})),
            execution_model=ExecutionModel(**strategy_data.get("execution_model", {})),
        )
        analysis = analyze_backtest_result(definition, result_data)
        return _json_response(True, data=analysis)
    except Exception as e:
        logger.error("Backtest analysis error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/quantlab/comprehensive-metrics")
async def get_comprehensive_metrics(
    request: Request,
    symbol: str = Query(..., max_length=20),
    strategy: str = Query(..., max_length=50),
):
    try:
        from core.backtest import BacktestEngine
        from core.backtest.enhanced_metrics import compute_comprehensive_metrics
        from core.strategies import STRATEGY_REGISTRY
        from core.data_fetcher import get_fetcher

        if strategy not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"策略{strategy}不存在")

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 60:
            return _json_response(False, error="数据不足")

        engine = BacktestEngine()
        result = await asyncio.to_thread(engine.run, STRATEGY_REGISTRY[strategy](), df, symbol)
        metrics = compute_comprehensive_metrics(
            equity_curve=result.equity_curve,
            dates=result.dates,
            trades=result.trades,
            initial_capital=1_000_000,
        )
        return _json_response(True, data={
            "returns": {
                "total_return": metrics.returns.total_return,
                "cagr": metrics.returns.cagr,
                "buy_hold_return": metrics.returns.buy_hold_return,
                "alpha": metrics.returns.alpha,
                "exposure_time_pct": metrics.returns.exposure_time_pct,
            },
            "risk": {
                "max_drawdown": metrics.risk.max_drawdown,
                "max_drawdown_duration_days": metrics.risk.max_drawdown_duration_days,
                "avg_drawdown": metrics.risk.avg_drawdown,
                "annual_volatility": metrics.risk.annual_volatility,
                "downside_deviation": metrics.risk.downside_deviation,
                "var_95": metrics.risk.var_95,
                "cvar_95": metrics.risk.cvar_95,
            },
            "risk_adjusted": {
                "sharpe_ratio": metrics.risk_adjusted.sharpe_ratio,
                "sortino_ratio": metrics.risk_adjusted.sortino_ratio,
                "calmar_ratio": metrics.risk_adjusted.calmar_ratio,
                "omega_ratio": metrics.risk_adjusted.omega_ratio,
                "profit_factor": metrics.risk_adjusted.profit_factor,
            },
            "trades": {
                "total_trades": metrics.trades.total_trades,
                "win_rate": metrics.trades.win_rate,
                "avg_win_avg_loss": metrics.trades.avg_win_avg_loss,
                "expectancy": metrics.trades.expectancy,
                "avg_trade_duration": metrics.trades.avg_trade_duration,
                "max_consecutive_wins": metrics.trades.max_consecutive_wins,
                "max_consecutive_losses": metrics.trades.max_consecutive_losses,
                "trades_per_year": metrics.trades.trades_per_year,
            },
            "distribution": {
                "skewness": metrics.distribution.skewness,
                "kurtosis": metrics.distribution.kurtosis,
                "tail_ratio": metrics.distribution.tail_ratio,
                "monthly_return_heatmap": metrics.distribution.monthly_return_heatmap,
                "return_histogram": metrics.distribution.return_histogram,
            },
            "guardrail_warnings": metrics.guardrail_warnings,
            "disclaimer": "Past backtest results do not guarantee future performance. All metrics are subject to estimation error.",
        })
    except Exception as e:
        logger.error("Comprehensive metrics error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/quantlab/walk-forward")
async def walk_forward_analysis_endpoint(request: Request, body: WalkForwardRequest):
    try:
        from core.backtest import BacktestEngine
        from core.backtest.optimization import walk_forward_analysis
        from core.strategies import STRATEGY_REGISTRY
        from core.data_fetcher import get_fetcher

        strategy_name = body.strategy
        symbol = body.symbol
        is_window = body.is_window
        oos_window = body.oos_window
        base_params = body.base_params
        param_ranges = body.param_ranges
        metric = body.metric
        anchored = body.anchored

        if strategy_name not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"策略{strategy_name}不存在")

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < is_window + oos_window:
            return _json_response(False, error="数据不足")

        engine = BacktestEngine()
        result = await asyncio.to_thread(
            walk_forward_analysis,
            engine, STRATEGY_REGISTRY[strategy_name], df,
            is_window=is_window, oos_window=oos_window,
            anchored=anchored, metric=metric,
            base_params=base_params, param_ranges=param_ranges,
        )
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Walk-forward analysis error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/quantlab/auto-optimize")
async def auto_optimize_strategy(request: Request, body: AutoOptimizeRequest):
    try:
        from core.backtest import BacktestEngine
        from core.backtest.optimization import walk_forward_analysis, parameter_grid_scan
        from core.strategies import STRATEGY_REGISTRY
        from core.data_fetcher import get_fetcher

        strategy_name = body.strategy
        symbol = body.symbol
        is_window = body.is_window
        oos_window = body.oos_window
        metric = body.metric
        param_ranges = body.param_ranges

        if strategy_name not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"策略{strategy_name}不存在")

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < is_window + oos_window:
            return _json_response(False, error="数据不足")

        engine = BacktestEngine()
        strategy_cls = STRATEGY_REGISTRY[strategy_name]

        wfa_result = await asyncio.to_thread(
            walk_forward_analysis,
            engine, strategy_cls, df,
            is_window=is_window, oos_window=oos_window,
            metric=metric, param_ranges=param_ranges,
        )

        if "error" in wfa_result:
            return _json_response(False, error=wfa_result["error"])

        best_window_params = []
        for w in wfa_result.get("windows", []):
            if "best_params" in w and w.get("oos_sharpe", 0) > 0:
                best_window_params.append(w["best_params"])

        recommended_params = {}
        if best_window_params:
            all_keys = set()
            for p in best_window_params:
                all_keys.update(p.keys())
            for k in all_keys:
                vals = [p[k] for p in best_window_params if k in p]
                if vals:
                    if isinstance(vals[0], int):
                        recommended_params[k] = int(round(sum(vals) / len(vals)))
                    else:
                        recommended_params[k] = round(sum(vals) / len(vals), 4)

        return _json_response(True, data={
            "wfa_result": wfa_result,
            "recommended_params": recommended_params,
            "n_profitable_windows": len(best_window_params),
            "curve_fitted": wfa_result.get("curve_fitted", False),
        })
    except Exception as e:
        logger.error("Auto-optimize error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/quantlab/strategy-health")
async def strategy_health_monitor(request: Request, symbol: str = Query("000001", max_length=20)):
    try:
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY
        from core.data_fetcher import get_fetcher

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="1y", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 60:
            return _json_response(False, error="数据不足，至少需要60根K线")

        engine = BacktestEngine()
        health_reports = []

        for name, cls in STRATEGY_REGISTRY.items():
            try:
                result = await asyncio.to_thread(engine.run, cls(), df, symbol)
                sharpe = float(result.sharpe_ratio) if hasattr(result, "sharpe_ratio") else 0.0
                max_dd = float(result.max_drawdown) if hasattr(result, "max_drawdown") else 0.0
                total_ret = float(result.total_return) if hasattr(result, "total_return") else 0.0
                win_rate = float(result.win_rate) if hasattr(result, "win_rate") else 0.0

                status = "healthy"
                issues = []
                if sharpe < 0:
                    status = "degraded"
                    issues.append("negative_sharpe")
                if max_dd < -0.3:
                    status = "degraded" if status == "healthy" else status
                    issues.append("excessive_drawdown")
                if win_rate < 0.3 and result.total_trades > 5:
                    status = "degraded" if status == "healthy" else status
                    issues.append("low_win_rate")

                health_reports.append({
                    "strategy": name,
                    "status": status,
                    "sharpe": round(sharpe, 4),
                    "max_drawdown": round(max_dd, 4),
                    "total_return": round(total_ret, 4),
                    "win_rate": round(win_rate, 4),
                    "total_trades": int(result.total_trades) if hasattr(result, "total_trades") else 0,
                    "issues": issues,
                })
            except Exception as e:
                health_reports.append({
                    "strategy": name,
                    "status": "error",
                    "error": str(e)[:100],
                })

        healthy_count = sum(1 for r in health_reports if r["status"] == "healthy")
        degraded_count = sum(1 for r in health_reports if r["status"] == "degraded")
        error_count = sum(1 for r in health_reports if r["status"] == "error")

        return _json_response(True, data={
            "symbol": symbol,
            "total_strategies": len(health_reports),
            "healthy": healthy_count,
            "degraded": degraded_count,
            "errors": error_count,
            "reports": health_reports,
        })
    except Exception as e:
        logger.error("Strategy health monitor error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/quantlab/compare-strategies")
async def compare_strategies(request: Request, body: CompareStrategiesRequest):
    try:
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY
        from core.data_fetcher import get_fetcher

        symbol = body.symbol
        strategy_names = body.strategies
        if not strategy_names:
            return _json_response(False, error="请提供策略列表")

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 60:
            return _json_response(False, error="数据不足")

        results = []
        for name in strategy_names[:10]:
            if name not in STRATEGY_REGISTRY:
                continue
            try:
                engine = BacktestEngine()
                result = await asyncio.to_thread(engine.run, STRATEGY_REGISTRY[name](), df, symbol)
                summary = result.get_performance_summary()
                summary["sharpe_per_dd"] = round(result.sharpe_ratio / max(result.max_drawdown, 1e-9), 2)
                results.append(summary)
            except Exception as e:
                logger.debug("Compare strategy %s failed: %s", name, e)

        results.sort(key=lambda x: x.get("sharpe", 0), reverse=True)
        pareto = min(results, key=lambda x: -x.get("sharpe_per_dd", 0)) if results else None
        return _json_response(True, data={
            "comparison": results,
            "pareto_optimal": pareto,
            "ranked_by": "sharpe_ratio",
        })
    except Exception as e:
        logger.error("Strategy comparison error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/quantlab/sensitivity-heatmap")
async def sensitivity_heatmap(request: Request, body: SensitivityHeatmapRequest):
    try:
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY
        from core.data_fetcher import get_fetcher

        strategy_name = body.strategy
        symbol = body.symbol
        param_x = body.param_x
        param_x_values = body.param_x_values
        param_y = body.param_y
        param_y_values = body.param_y_values
        metric = body.metric

        if strategy_name not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"策略{strategy_name}不存在")

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 60:
            return _json_response(False, error="数据不足")

        engine = BacktestEngine()
        strategy_cls = STRATEGY_REGISTRY[strategy_name]

        heatmap = []
        valid_metrics = []
        for yv in param_y_values:
            row = []
            for xv in param_x_values:
                try:
                    yv_typed = int(yv) if yv == int(yv) else yv
                    xv_typed = int(xv) if xv == int(xv) else xv
                    strat = strategy_cls(**{param_x: xv_typed, param_y: yv_typed})
                    bt_result = await asyncio.to_thread(engine.run, strat, df, symbol)
                    val = getattr(bt_result, metric, None)
                    if val is not None and hasattr(val, "__float__"):
                        val = round(float(val), 4)
                    else:
                        val = None
                    row.append(val)
                    if val is not None:
                        valid_metrics.append(val)
                except Exception as e:
                    logger.debug("Heatmap %s=%s, %s=%s error: %s", param_x, xv, param_y, yv, e)
                    row.append(None)
            heatmap.append(row)

        metric_min = min(valid_metrics) if valid_metrics else 0
        metric_max = max(valid_metrics) if valid_metrics else 0
        metric_mean = round(sum(valid_metrics) / len(valid_metrics), 4) if valid_metrics else 0

        best_idx = None
        best_val = None
        for yi, row in enumerate(heatmap):
            for xi, val in enumerate(row):
                if val is not None and (best_val is None or val > best_val):
                    best_val = val
                    best_idx = (yi, xi)

        best_params = None
        if best_idx is not None:
            yi, xi = best_idx
            best_params = {
                param_x: param_x_values[xi],
                param_y: param_y_values[yi],
                metric: best_val,
            }

        return _json_response(True, data={
            "param_x": param_x,
            "param_x_values": param_x_values,
            "param_y": param_y,
            "param_y_values": param_y_values,
            "metric": metric,
            "heatmap": heatmap,
            "statistics": {
                "min": round(metric_min, 4) if valid_metrics else None,
                "max": round(metric_max, 4) if valid_metrics else None,
                "mean": metric_mean,
                "range": round(metric_max - metric_min, 4) if valid_metrics else None,
            },
            "best_params": best_params,
            "total_combinations": len(param_x_values) * len(param_y_values),
            "valid_combinations": len(valid_metrics),
        })
    except Exception as e:
        logger.error("Sensitivity heatmap error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/quantlab/signal-replay")
async def signal_replay(request: Request, body: SignalReplayRequest):
    try:
        from core.strategies import STRATEGY_REGISTRY
        from core.data_fetcher import get_fetcher

        strategy_name = body.strategy
        symbol = body.symbol
        start_bar = body.start_bar
        end_bar = body.end_bar
        params = body.params

        if strategy_name not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"策略{strategy_name}不存在")

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 2:
            return _json_response(False, error="数据不足")

        strategy_cls = STRATEGY_REGISTRY[strategy_name]
        if params:
            typed_params = {}
            for k, v in params.items():
                typed_params[k] = int(v) if isinstance(v, float) and v == int(v) else v
            strat = strategy_cls(**typed_params)
        else:
            strat = strategy_cls()

        strat.reset()

        end_bar = min(end_bar, len(df))
        start_bar = min(start_bar, end_bar - 1)

        replay_steps = []
        for i in range(start_bar, end_bar):
            row = df.iloc[i]
            bar = {
                "open": float(row.get("open", 0)) if pd.notna(row.get("open")) else 0,
                "high": float(row.get("high", 0)) if pd.notna(row.get("high")) else 0,
                "low": float(row.get("low", 0)) if pd.notna(row.get("low")) else 0,
                "close": float(row.get("close", 0)) if pd.notna(row.get("close")) else 0,
                "volume": float(row.get("volume", 0)) if pd.notna(row.get("volume")) else 0,
                "date": str(row.get("date", ""))[:10] if "date" in df.columns else "",
            }

            sigs = strat.on_bar(bar, {})
            signals = []
            for sig in sigs:
                action = sig.get("action", "hold")
                if action in ("buy", "sell"):
                    signals.append({
                        "action": action,
                        "confidence": sig.get("confidence", 0.5),
                        "reason": sig.get("reason", ""),
                        "position_pct": sig.get("position_pct", 0.0),
                        "stop_loss": sig.get("stop_loss", 0.0),
                        "take_profit": sig.get("take_profit", 0.0),
                    })

            step = {
                "bar_index": i,
                "date": bar["date"],
                "close": bar["close"],
                "signals": signals,
            }
            replay_steps.append(step)

        buy_count = sum(1 for s in replay_steps for sig in s["signals"] if sig["action"] == "buy")
        sell_count = sum(1 for s in replay_steps for sig in s["signals"] if sig["action"] == "sell")

        return _json_response(True, data={
            "strategy": strategy_name,
            "symbol": symbol,
            "start_bar": start_bar,
            "end_bar": end_bar,
            "total_bars": len(df),
            "replay_steps": replay_steps,
            "summary": {
                "bars_replayed": len(replay_steps),
                "buy_signals": buy_count,
                "sell_signals": sell_count,
                "signal_density": round((buy_count + sell_count) / max(len(replay_steps), 1), 4),
            },
        })
    except Exception as e:
        logger.error("Signal replay error: %s", e)
        return _json_response(False, error=safe_error(e))
