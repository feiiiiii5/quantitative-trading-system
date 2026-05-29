from __future__ import annotations

import asyncio
import logging
from typing import Any

import pandas as pd
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from api.dependencies import FetcherDep
from api.routers.models import (
    AnalyzeBacktestRequest,
    AutoOptimizeRequest,
    CompareStrategiesRequest,
    DiagnoseRequest,
    GarchVolatilityRequest,
    PairMiningRequest,
    PortfolioAnalyticsRequest,
    RegimeDetectRequest,
    SensitivityHeatmapRequest,
    SignalReplayRequest,
    WalkForwardRequest,
)
from api.utils import json_response as _json_response
from api.utils import period_to_history as _period_to_history
from api.utils import safe_error

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
            ExecutionModel,
            IndicatorSpec,
            MarketType,
            ParameterSpec,
            RiskManagement,
            SignalLogic,
            StrategyDefinition,
            StrategyMeta,
            Timeframe,
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
async def diagnose_strategy(fetcher: FetcherDep, body: DiagnoseRequest):
    try:
        from core.backtest import BacktestEngine
        from core.backtest.enhanced_metrics import compute_comprehensive_metrics
        from core.strategies import STRATEGY_REGISTRY
        from core.strategy_analyzer import analyze_backtest_result
        from core.strategy_schema import (
            MarketType,
            StrategyDefinition,
            StrategyMeta,
        )

        strategy_name = body.strategy
        symbol = body.symbol
        if strategy_name not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"策略{strategy_name}不存在")

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
            "max_dd_pct": round(result.max_drawdown, 2),
            "win_rate_pct": round(result.win_rate, 1),
        }

        return _json_response(True, data={
            "quick_stats": quick_stats,
            "comprehensive_metrics": {
                "returns": dict(metrics.returns.__dict__.items()),
                "risk": dict(metrics.risk.__dict__.items()),
                "risk_adjusted": dict(metrics.risk_adjusted.__dict__.items()),
                "trades": dict(metrics.trades.__dict__.items()),
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
        from core.strategy_analyzer import analyze_strategy
        from core.strategy_schema import (
            AssetClass,
            ExecutionModel,
            IndicatorSpec,
            MarketType,
            ParameterSpec,
            RiskManagement,
            SignalLogic,
            StrategyDefinition,
            StrategyMeta,
            Timeframe,
        )
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
        from core.strategy_analyzer import analyze_backtest_result
        from core.strategy_schema import (
            AssetClass,
            ExecutionModel,
            IndicatorSpec,
            MarketType,
            ParameterSpec,
            RiskManagement,
            SignalLogic,
            StrategyDefinition,
            StrategyMeta,
            Timeframe,
        )

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
    fetcher: FetcherDep,
    symbol: str = Query(..., max_length=20),
    strategy: str = Query(..., max_length=50),
):
    try:
        from core.backtest import BacktestEngine
        from core.backtest.enhanced_metrics import compute_comprehensive_metrics
        from core.strategies import STRATEGY_REGISTRY

        if strategy not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"策略{strategy}不存在")

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
async def walk_forward_analysis_endpoint(fetcher: FetcherDep, body: WalkForwardRequest):
    try:
        from core.backtest import BacktestEngine
        from core.backtest.optimization import walk_forward_analysis
        from core.strategies import STRATEGY_REGISTRY

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
async def auto_optimize_strategy(fetcher: FetcherDep, body: AutoOptimizeRequest):
    try:
        from core.backtest import BacktestEngine
        from core.backtest.optimization import walk_forward_analysis
        from core.strategies import STRATEGY_REGISTRY

        strategy_name = body.strategy
        symbol = body.symbol
        is_window = body.is_window
        oos_window = body.oos_window
        metric = body.metric
        param_ranges = body.param_ranges

        if strategy_name not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"策略{strategy_name}不存在")

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
async def strategy_health_monitor(fetcher: FetcherDep, symbol: str = Query("000001", max_length=20)):
    try:
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY

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
async def compare_strategies(fetcher: FetcherDep, body: CompareStrategiesRequest):
    try:
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY

        symbol = body.symbol
        strategy_names = body.strategies
        if not strategy_names:
            return _json_response(False, error="请提供策略列表")

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
async def sensitivity_heatmap(fetcher: FetcherDep, body: SensitivityHeatmapRequest):
    try:
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY

        strategy_name = body.strategy
        symbol = body.symbol
        param_x = body.param_x
        param_x_values = body.param_x_values
        param_y = body.param_y
        param_y_values = body.param_y_values
        metric = body.metric

        if strategy_name not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"策略{strategy_name}不存在")

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
                    val = round(float(val), 4) if val is not None and hasattr(val, "__float__") else None
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
async def signal_replay(fetcher: FetcherDep, body: SignalReplayRequest):
    try:
        from core.strategies import STRATEGY_REGISTRY

        strategy_name = body.strategy
        symbol = body.symbol
        start_bar = body.start_bar
        end_bar = body.end_bar
        params = body.params

        if strategy_name not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"策略{strategy_name}不存在")

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


class CrossSectionalRankRequest(BaseModel):
    symbols: str = Field(..., min_length=1, max_length=500, description="逗号分隔的股票代码")
    period: str = Field("6m", max_length=5, description="训练数据时间范围")
    forward_period: int = Field(5, ge=1, le=60, description="前向收益天数")
    n_top: int = Field(10, ge=1, le=50, description="推荐股票数量")


@router.post("/quantlab/cross-sectional-rank")
async def cross_sectional_rank(fetcher: FetcherDep, body: CrossSectionalRankRequest):
    """横截面因子排名：使用LightGBM对股票进行多因子综合评分和排名"""
    try:
        from core.cross_sectional_ranker import LGBM_AVAILABLE, CrossSectionalRanker

        if not LGBM_AVAILABLE:
            return _json_response(False, error="LightGBM未安装，请执行: pip install lightgbm")

        symbol_list = [s.strip() for s in body.symbols.split(",") if s.strip()]
        if len(symbol_list) < 10:
            return _json_response(False, error="至少需要10只股票进行横截面排名")

        symbol_list = symbol_list[:50]

        history_map = await fetcher.get_history_batch(
            symbol_list, "1y", "daily", "qfq"
        )

        price_data = {}
        for sym, df in history_map.items():
            if df is not None and len(df) >= 60:
                price_data[sym] = df

        if len(price_data) < 10:
            return _json_response(False, error="有效数据不足，至少需要10只股票有60日以上数据")

        from core.indicators import compute_macd, compute_rsi

        factor_rows = []
        for sym, df in price_data.items():
            close = df["close"].astype(float).values
            if len(close) < 30:
                continue

            returns = pd.Series(close).pct_change().dropna()
            if len(returns) < 20:
                continue

            momentum_5 = returns.rolling(5).mean().iloc[-1] if len(returns) >= 5 else 0.0
            momentum_10 = returns.rolling(10).mean().iloc[-1] if len(returns) >= 10 else 0.0
            momentum_20 = returns.rolling(20).mean().iloc[-1] if len(returns) >= 20 else 0.0

            vol_5 = returns.rolling(5).std().iloc[-1] if len(returns) >= 5 else 0.0
            vol_10 = returns.rolling(10).std().iloc[-1] if len(returns) >= 10 else 0.0
            vol_20 = returns.rolling(20).std().iloc[-1] if len(returns) >= 20 else 0.0

            rsi_val = compute_rsi(close, period=14)
            rsi = float(rsi_val[-1]) if len(rsi_val) > 0 else 50.0

            macd_result = compute_macd(close)
            macd_val = float(macd_result["macd"][-1]) if len(macd_result["macd"]) > 0 else 0.0
            macd_signal = float(macd_result["signal"][-1]) if len(macd_result["signal"]) > 0 else 0.0

            avg_volume = float(df["volume"].astype(float).tail(20).mean()) if "volume" in df.columns else 0.0

            factor_rows.append({
                "symbol": sym,
                "momentum_5": momentum_5,
                "momentum_10": momentum_10,
                "momentum_20": momentum_20,
                "vol_5": vol_5,
                "vol_10": vol_10,
                "vol_20": vol_20,
                "rsi": rsi,
                "macd": macd_val,
                "macd_signal": macd_signal,
                "avg_volume": avg_volume,
            })

        if len(factor_rows) < 10:
            return _json_response(False, error="有效因子数据不足")

        factor_df = pd.DataFrame(factor_rows).set_index("symbol")

        forward_returns = {}
        for sym in factor_df.index:
            if sym in price_data:
                close = price_data[sym]["close"].astype(float).values
                if len(close) > body.forward_period:
                    forward_returns[sym] = (close[-1] - close[-body.forward_period - 1]) / close[-body.forward_period - 1]
                else:
                    forward_returns[sym] = 0.0

        forward_ret_series = pd.Series(forward_returns, name="forward_return")

        ranker = CrossSectionalRanker()
        train_info = ranker.fit(factor_df, forward_ret_series)

        ranked = ranker.predict(factor_df)
        top_stocks = ranker.select_top_stocks(factor_df, n_stocks=body.n_top)

        importance = ranker.feature_importance()

        return _json_response(True, data={
            "top_stocks": [
                {"symbol": sym, "rank_score": round(float(ranked.get(sym, 0)), 4)}
                for sym in top_stocks
            ],
            "all_rankings": [
                {"symbol": sym, "rank_score": round(float(score), 4)}
                for sym, score in sorted(ranked.items(), key=lambda x: x[1], reverse=True)
            ],
            "feature_importance": {
                name: round(float(imp), 4)
                for name, imp in importance.head(10).items()
            },
            "train_info": {
                "n_samples": train_info["n_samples"],
                "n_train": train_info["n_train"],
                "n_val": train_info["n_val"],
                "best_iteration": train_info["best_iteration"],
            },
            "factors_used": list(factor_df.columns),
        })
    except Exception as e:
        logger.error("Cross-sectional rank error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/quantlab/regime-detect")
async def regime_detect(fetcher: FetcherDep, body: RegimeDetectRequest):
    """HMM市场状态检测：识别当前市场处于牛市/熊市/中性状态"""
    try:
        symbol = body.symbol.strip()
        df = await fetcher.get_history(symbol, period=body.period, kline_type="daily", adjust="qfq")
        if df is None or df.empty or "close" not in df.columns:
            return _json_response(False, error="无法获取行情数据")

        close = pd.to_numeric(df["close"], errors="coerce").dropna()
        if len(close) < 60:
            return _json_response(False, error="数据不足，至少需要60个交易日")

        returns = close.pct_change().dropna().values
        from core.volatility import detect_regime_hmm
        result = detect_regime_hmm(returns, n_states=body.n_states)

        if "error" in result:
            return _json_response(False, error=result["error"])

        return _json_response(True, data={
            "symbol": symbol,
            "period": body.period,
            "n_data_points": len(returns),
            "current_state": result["current_label"],
            "state_probabilities": result["state_probabilities"],
            "states": result["states"],
            "transition_matrix": result["transition_matrix"],
            "regime_history": result["regime_history"],
        })
    except Exception as e:
        logger.error("Regime detect error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/quantlab/volatility-garch")
async def volatility_garch(fetcher: FetcherDep, body: GarchVolatilityRequest):
    """GARCH波动率建模：估计当前和长期波动率，预测未来波动率"""
    try:
        symbol = body.symbol.strip()
        df = await fetcher.get_history(symbol, period=body.period, kline_type="daily", adjust="qfq")
        if df is None or df.empty or "close" not in df.columns:
            return _json_response(False, error="无法获取行情数据")

        close = pd.to_numeric(df["close"], errors="coerce").dropna()
        if len(close) < 30:
            return _json_response(False, error="数据不足，至少需要30个交易日")

        returns = close.pct_change().dropna().values
        from core.volatility import fit_garch
        result = fit_garch(returns, iterations=body.iterations)

        if "error" in result:
            return _json_response(False, error=result["error"])

        return _json_response(True, data={
            "symbol": symbol,
            "period": body.period,
            "n_data_points": len(returns),
            "current_volatility": result["current_volatility"],
            "long_run_volatility": result["long_run_volatility"],
            "persistence": result["persistence"],
            "garch_params": {
                "omega": result["omega"],
                "alpha": result["alpha"],
                "beta": result["beta"],
            },
            "forecasts": {
                "5d": result["forecast_5d"],
                "10d": result["forecast_10d"],
                "22d": result["forecast_22d"],
            },
            "forecast_series": result["forecast_series"],
            "volatility_history": result["volatility_history"],
            "regime": result["regime"],
        })
    except Exception as e:
        logger.error("GARCH volatility error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/quantlab/pair-mining")
async def pair_mining(fetcher: FetcherDep, body: PairMiningRequest):
    """统计套利配对挖掘：寻找协整股票对"""
    try:
        symbol_list = [s.strip() for s in body.symbols if s.strip()]
        if len(symbol_list) < 2:
            return _json_response(False, error="至少需要2只股票进行配对分析")
        symbol_list = symbol_list[:20]

        history_map = await fetcher.get_history_batch(
            symbol_list, _period_to_history(body.period), "daily", "qfq"
        )

        price_data = {}
        for sym, df in history_map.items():
            if df is not None and len(df) >= 30 and "close" in df.columns:
                price_data[sym] = pd.to_numeric(df["close"], errors="coerce").dropna()

        if len(price_data) < 2:
            return _json_response(False, error="有效数据不足，至少需要2只股票有足够历史数据")

        prices_df = pd.DataFrame(price_data)
        from core.statistical_arbitrage import PairMiningEngine
        engine = PairMiningEngine(pvalue_threshold=body.pvalue_threshold, method=body.method)
        results = engine.find_cointegrated_pairs(prices_df, list(price_data.keys()))

        return _json_response(True, data={
            "method": body.method,
            "n_symbols_tested": len(price_data),
            "n_pairs_found": len(results),
            "pairs": [r.to_dict() for r in results],
        })
    except Exception as e:
        logger.error("Pair mining error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/quantlab/portfolio-analytics")
async def portfolio_analytics(fetcher: FetcherDep, body: PortfolioAnalyticsRequest):
    """统一组合分析管道：一次性完成市场状态检测、风险平价优化、蒙特卡洛VaR、因子归因"""
    try:
        symbol_list = [s.strip() for s in body.symbols.split(",") if s.strip()]
        if len(symbol_list) < 2:
            return _json_response(False, error="至少需要2只股票")
        symbol_list = symbol_list[:20]

        history_map = await fetcher.get_history_batch(
            symbol_list, _period_to_history(body.period), "daily", "qfq"
        )

        price_data = {}
        for sym, df in history_map.items():
            if df is not None and len(df) >= 30 and "close" in df.columns:
                price_data[sym] = pd.to_numeric(df["close"], errors="coerce").dropna()

        if len(price_data) < 2:
            return _json_response(False, error="有效数据不足，至少需要2只股票有足够历史数据")

        min_len = min(len(v) for v in price_data.values())
        prices_df = pd.DataFrame({sym: v.values[-min_len:] for sym, v in price_data.items()})
        returns_df = prices_df.pct_change().dropna()

        result: dict[str, Any] = {
            "symbols": list(price_data.keys()),
            "period": body.period,
            "n_observations": len(returns_df),
        }

        if body.include_regime and len(returns_df) >= 60:
            from core.volatility import detect_regime_hmm
            portfolio_returns = returns_df.mean(axis=1).values
            regime = detect_regime_hmm(portfolio_returns, n_states=body.n_regime_states)
            if "error" not in regime:
                result["regime"] = {
                    "current_state": regime["current_label"],
                    "state_probabilities": regime["state_probabilities"],
                    "states": regime["states"],
                }

        if body.include_risk_parity:
            from core.risk_parity_portfolio import RiskParityPortfolio
            rp = RiskParityPortfolio(symbols=list(price_data.keys()))
            for _, row in returns_df.iterrows():
                rp.update_returns(row.values)
            state = rp.compute_target_weights()
            result["risk_parity"] = {
                "weights": state.weights,
                "risk_contributions": state.risk_contributions,
                "portfolio_volatility": state.portfolio_volatility,
                "rebalance_needed": state.rebalance_needed,
                "max_drift": state.max_drift,
            }

        if body.include_var:
            from core.monte_carlo_var import MonteCarloVaR
            mc = MonteCarloVaR(n_simulations=body.n_simulations, time_horizon=body.time_horizon)
            mc_result = mc.simulate(prices_df)
            if mc_result.is_valid:
                result["var"] = {
                    "var_95": round(mc_result.var_95, 6),
                    "var_99": round(mc_result.var_99, 6),
                    "cvar_95": round(mc_result.cvar_95, 6),
                    "cvar_99": round(mc_result.cvar_99, 6),
                    "mean_return": round(mc_result.mean_portfolio_return, 6),
                    "std_return": round(mc_result.std_portfolio_return, 6),
                    "n_simulations": mc_result.n_simulations,
                }

        if body.include_factor_attribution and len(price_data) >= 3:
            try:
                from core.factor_model import FactorModel
                fm = FactorModel()
                factor_returns = fm.construct_factor_returns(returns_df)
                if factor_returns is not None and len(factor_returns) > 0:
                    exposures = fm.estimate_exposures(returns_df, factor_returns)
                    attribution = fm.attribute_returns(returns_df, factor_returns, exposures)
                    if attribution.is_valid:
                        result["factor_attribution"] = {
                            "total_return": round(attribution.total_return, 6),
                            "factor_contributions": {k: round(v, 6) for k, v in attribution.factor_contributions.items()},
                            "specific_return": round(attribution.specific_return, 6),
                        }
            except Exception as e:
                logger.debug("Factor attribution skipped: %s", e)

        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Portfolio analytics error: %s", e)
        return _json_response(False, error=safe_error(e))
