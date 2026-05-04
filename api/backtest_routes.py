import logging
import re
from typing import Optional

from fastapi import APIRouter, Path, Query, Request
from pydantic import BaseModel, Field, field_validator

from api.utils import json_response as _json_response, safe_error

logger = logging.getLogger(__name__)
backtest_router = APIRouter()

_SYMBOL_RE = re.compile(r"^[0-9]{6}\.[A-Z]{2}$|^[0-9]{6}$|^[A-Z]+$")


class BacktestRunRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")
    strategy_type: str = Field("adaptive", max_length=30, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    start_date: str = Field("2024-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field("2025-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$")
    initial_capital: float = 1000000
    commission: float = 0.0003

    @field_validator("initial_capital")
    @classmethod
    def validate_capital(cls, v: float) -> float:
        if v < 10000 or v > 1e9:
            raise ValueError("初始资金范围: 1万-10亿")
        return v

    @field_validator("commission")
    @classmethod
    def validate_commission(cls, v: float) -> float:
        if v < 0 or v > 0.01:
            raise ValueError("佣金费率范围: 0-1%")
        return v


class BacktestAdvancedRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")
    strategy_type: str = Field("adaptive", max_length=30, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    strategy_name: Optional[str] = Field(None, max_length=30, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    start_date: str = Field("2022-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field("2024-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$")
    initial_capital: float = 1000000
    enable_short: bool = False
    leverage: float = 1.0
    monte_carlo: bool = False
    n_simulations: int = 500
    sensitivity: bool = False
    walk_forward: bool = False

    @field_validator("initial_capital")
    @classmethod
    def validate_capital(cls, v: float) -> float:
        if v < 10000 or v > 1e9:
            raise ValueError("初始资金范围: 1万-10亿")
        return v

    @field_validator("leverage")
    @classmethod
    def validate_leverage(cls, v: float) -> float:
        if v < 0.1 or v > 5.0:
            raise ValueError("杠杆范围: 0.1-5.0")
        return v

    @field_validator("n_simulations")
    @classmethod
    def validate_simulations(cls, v: int) -> int:
        if v < 10 or v > 5000:
            raise ValueError("模拟次数范围: 10-5000")
        return v


@backtest_router.get("/backtest/strategies")
async def get_backtest_strategies(request: Request):
    try:
        from core.strategies import STRATEGY_REGISTRY
        strategy_info = {}
        seen = set()
        for alias, cls in STRATEGY_REGISTRY.items():
            real_name = cls.__name__
            if real_name in seen:
                continue
            seen.add(real_name)
            try:
                inst = cls()
                info = inst.get_info()
                info["param_space"] = cls.get_param_space()
                strategy_info[real_name] = info
            except Exception:
                strategy_info[real_name] = {"name": real_name, "type": "unknown"}
        strategy_info["AdaptiveEngine"] = {
            "name": "自适应量化策略引擎",
            "type": "adaptive",
            "param_space": {},
        }
        return _json_response(True, data=strategy_info)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@backtest_router.post("/backtest/run")
async def run_backtest(
    request: Request,
    body: BacktestRunRequest,
):
    try:
        from core.backtest import run_backtest as run_bt
        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error=f"无法获取 {body.symbol} 的历史数据")

        result = await _run_single_or_adaptive(body.strategy_type, body.symbol, body.start_date, body.end_date, body.initial_capital, df)

        if "error" in result:
            return _json_response(False, error=result["error"])

        return _json_response(True, data=result)
    except Exception as e:
        logger.error(f"backtest run error: {e}", exc_info=True)
        return _json_response(False, error=safe_error(e))


@backtest_router.get("/backtest/result/{task_id}")
async def get_backtest_result(request: Request, task_id: str):
    return _json_response(False, error="回测结果查询暂不支持")


@backtest_router.get("/backtest/compare")
async def compare_strategies(
    request: Request,
    symbol: str = Query(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    start_date: str = Query("2024-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query("2025-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    period: str = Query("1y", max_length=5),
):
    try:
        from core.strategies import STRATEGY_REGISTRY
        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error="数据不足")

        import pandas as pd
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])

        work_df = df.copy()
        if "date" in work_df.columns:
            work_df = work_df[(work_df["date"] >= start_date) & (work_df["date"] <= end_date)].reset_index(drop=True)

        if len(work_df) < 30:
            work_df = df.tail(252).reset_index(drop=True)
            if len(work_df) < 30:
                return _json_response(False, error="数据不足，请更换股票代码或时间范围")

        engine = request.app.state.backtest_engine
        strategies = request.app.state.composite_strategy.strategies
        results = engine.run_multi(strategies, work_df)

        comparison = []
        for name, result in results.items():
            comparison.append({
                "strategy_name": result.strategy_name,
                "total_return": round(result.total_return, 4) if result.total_return else 0,
                "annual_return": round(result.annual_return, 4) if result.annual_return else 0,
                "sharpe_ratio": round(result.sharpe_ratio, 2) if result.sharpe_ratio else 0,
                "max_drawdown": round(result.max_drawdown, 4) if result.max_drawdown else 0,
                "win_rate": round(result.win_rate, 2) if result.win_rate else 0,
                "profit_factor": round(result.profit_factor, 2) if result.profit_factor else 0,
                "total_trades": result.total_trades,
            })

        comparison.sort(key=lambda x: x["total_return"], reverse=True)
        return _json_response(True, data=comparison)
    except Exception as e:
        logger.error(f"compare strategies error: {e}", exc_info=True)
        return _json_response(False, error=safe_error(e))


@backtest_router.get("/backtest/recommend")
async def recommend_strategy(
    request: Request,
    symbol: str = Query(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    start_date: str = Query("2024-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query("2025-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    try:
        import numpy as np
        import pandas as pd
        from core.indicators import calc_atr, calc_adx
        from core.adaptive_strategy import classify_market_regime, REGIME_LABELS, STRATEGY_ALLOCATION, MarketRegime
        from core.strategies import STRATEGY_REGISTRY

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error="无法获取历史数据")

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])

        work_df = df.copy()
        if "date" in work_df.columns:
            work_df = work_df[(work_df["date"] >= start_date) & (work_df["date"] <= end_date)].reset_index(drop=True)

        if len(work_df) < 30:
            work_df = df.tail(252).reset_index(drop=True)
            if len(work_df) < 30:
                return _json_response(False, error="数据不足，请更换股票代码或时间范围")

        c = work_df["close"].values.astype(float)
        h = work_df["high"].values.astype(float)
        low_arr = work_df["low"].values.astype(float)
        v = work_df["volume"].values.astype(float) if "volume" in work_df.columns else np.ones(len(c))

        returns = np.diff(c) / np.where(c[:-1] > 0, c[:-1], 1)
        returns = np.where(np.isfinite(returns), returns, 0)

        hist_vol = float(np.std(returns) * np.sqrt(252))
        trend = float((c[-1] - c[0]) / c[0] * 100) if c[0] > 0 else 0
        total_return = trend

        adx_arr = calc_adx(h, low_arr, c, period=14)
        last_adx = float(adx_arr[-1]) if not np.isnan(adx_arr[-1]) else 20.0

        atr_arr = calc_atr(h, low_arr, c, period=14)
        avg_atr_pct = float(np.nanmean(atr_arr[-20:]) / np.mean(c[-20:]) * 100) if len(c) >= 20 else 2.0

        ma5 = float(np.mean(c[-5:]))
        ma20 = float(np.mean(c[-20:])) if len(c) >= 20 else ma5
        ma60 = float(np.mean(c[-60:])) if len(c) >= 60 else ma20
        ma_alignment = "bullish" if ma5 > ma20 > ma60 else ("bearish" if ma5 < ma20 < ma60 else "neutral")

        rsi_period = 14
        if len(returns) >= rsi_period:
            delta = np.diff(c)
            gain = np.where(delta > 0, delta, 0)
            loss_arr = np.where(delta < 0, -delta, 0)
            avg_gain = np.mean(gain[-rsi_period:])
            avg_loss = np.mean(loss_arr[-rsi_period:])
            rs = avg_gain / max(avg_loss, 1e-9)
            rsi = 100 - 100 / (1 + rs)
        else:
            rsi = 50.0

        vol_ma20 = float(np.mean(v[-20:])) if len(v) >= 20 else 1
        vol_ratio = float(v[-1]) / max(vol_ma20, 1) if vol_ma20 > 0 else 1.0

        bb_mid = float(np.mean(c[-20:])) if len(c) >= 20 else float(c[-1])
        bb_std = float(np.std(c[-20:])) if len(c) >= 20 else 0
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_position = (float(c[-1]) - bb_lower) / max(bb_upper - bb_lower, 1e-9)

        regimes = classify_market_regime(work_df)
        current_regime = regimes[-1] if regimes else MarketRegime.LOW_VOLATILITY_CONSOLIDATION
        regime_name = REGIME_LABELS.get(current_regime, "未知")

        regime_counts = {}
        for r in regimes[-60:]:
            label = REGIME_LABELS.get(r, "未知")
            regime_counts[label] = regime_counts.get(label, 0) + 1
        dominant_regime = max(regime_counts, key=regime_counts.get) if regime_counts else "未知"

        analysis = {
            "trend": round(trend, 2),
            "volatility": round(hist_vol, 4),
            "adx": round(last_adx, 2),
            "atr_pct": round(avg_atr_pct, 4),
            "rsi": round(rsi, 2),
            "ma_alignment": ma_alignment,
            "volume_ratio": round(vol_ratio, 2),
            "bb_position": round(bb_position, 4),
            "regime": regime_name,
            "dominant_regime": dominant_regime,
        }

        recommendations = []
        regime_alloc = STRATEGY_ALLOCATION.get(current_regime, {})
        regime_strategies = regime_alloc.get("strategies", [])
        regime_weights = regime_alloc.get("weights", [])

        for idx, strategy_cls in enumerate(regime_strategies):
            w = regime_weights[idx] if idx < len(regime_weights) else 0.1
            name = strategy_cls.__name__
            display_name = name
            for alias, cls in STRATEGY_REGISTRY.items():
                if cls == strategy_cls:
                    display_name = alias
                    break

            reasons = []
            if current_regime in (MarketRegime.STRONG_TREND_UP, MarketRegime.MILD_TREND_UP):
                reasons.append(f"当前市场处于{regime_name}，趋势策略表现更优")
            elif current_regime in (MarketRegime.HIGH_VOLATILITY_RANGE, MarketRegime.LOW_VOLATILITY_CONSOLIDATION):
                reasons.append(f"当前市场处于{regime_name}，震荡策略表现更优")
            elif current_regime in (MarketRegime.MILD_TREND_DOWN, MarketRegime.STRONG_TREND_DOWN):
                reasons.append(f"当前市场处于{regime_name}，防御策略表现更优")
            elif current_regime == MarketRegime.BEAR_TRAP:
                reasons.append("检测到空头陷阱，反转策略表现更优")
            elif current_regime == MarketRegime.DISTRIBUTION_TOP:
                reasons.append("检测到派发顶部信号，减仓策略表现更优")

            if last_adx > 30:
                reasons.append(f"ADX={last_adx:.1f}趋势较强")
            elif last_adx < 20:
                reasons.append(f"ADX={last_adx:.1f}趋势较弱，适合均值回归")

            if hist_vol > 0.30:
                reasons.append(f"波动率{hist_vol:.1%}偏高，注意风险控制")
            elif hist_vol < 0.15:
                reasons.append(f"波动率{hist_vol:.1%}偏低，适合布局突破")

            if rsi < 30:
                reasons.append(f"RSI={rsi:.0f}超卖区间")
            elif rsi > 70:
                reasons.append(f"RSI={rsi:.0f}超买区间")

            recommendations.append({
                "strategy": display_name,
                "strategy_class": name,
                "score": round(w, 4),
                "reasons": reasons,
            })

        recommendations.sort(key=lambda x: x["score"], reverse=True)

        adaptive_reason = "当前市场环境复杂，自适应引擎可根据市场状态自动切换策略组合"
        recommendations.insert(0, {
            "strategy": "adaptive",
            "strategy_class": "AdaptiveEngine",
            "score": 1.0,
            "reasons": [adaptive_reason, f"当前市场状态: {regime_name}", f"近期主导状态: {dominant_regime}"],
        })

        return _json_response(True, data={
            "analysis": analysis,
            "recommendations": recommendations[:6],
        })
    except Exception as e:
        logger.error(f"recommend strategy error: {e}", exc_info=True)
        return _json_response(False, error=safe_error(e))


async def _run_single_or_adaptive(strategy_type, symbol, start_date, end_date, initial_capital, df):
    import asyncio
    from core.backtest import run_backtest as run_bt

    if strategy_type == "composite" or strategy_type == "all":
        from core.backtest import BacktestEngine
        from core.strategies import CompositeStrategy
        engine = BacktestEngine(initial_capital=initial_capital)
        strategies = CompositeStrategy().strategies
        import pandas as pd
        work_df = df.copy()
        if "date" in work_df.columns:
            work_df["date"] = pd.to_datetime(work_df["date"], errors="coerce")
            work_df = work_df.dropna(subset=["date"])
            work_df = work_df[(work_df["date"] >= start_date) & (work_df["date"] <= end_date)].reset_index(drop=True)
        results = engine.run_multi(strategies, work_df)
        output = {}
        for name, result in results.items():
            output[name] = _serialize_result(result, initial_capital, df)
        return output

    result = await asyncio.to_thread(
        run_bt,
        symbol,
        strategy_type,
        start_date,
        end_date,
        initial_capital,
        None,
        df,
    )
    return result


def _serialize_result(result, initial_capital, df):
    import numpy as np
    equity_curve = []
    if result.equity_curve and result.dates:
        for i in range(min(len(result.dates), len(result.equity_curve))):
            equity_curve.append({"date": result.dates[i], "value": float(result.equity_curve[i])})

    return {
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
        "equity_curve": equity_curve[-500:] if equity_curve else [],
        "trades": result.trades[-100:] if result.trades else [],
    }
