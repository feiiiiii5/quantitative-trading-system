import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.factor_validity import FactorValidityMonitor, ModelValidityMonitor

from .engine import BacktestEngine
from .result import InsufficientDataError
from .simulation import _get_strategy_min_bars

logger = logging.getLogger(__name__)


@dataclass
class ICWindowResult:
    window: int
    ic: float
    rank_ic: float
    ic_ir: float
    n_observations: int
    factor_valid: bool
    weight_adjustment: float
    position_scale: float


@dataclass
class WalkForwardICResult:
    base_result: dict
    ic_windows: list[ICWindowResult] = field(default_factory=list)
    ic_summary: dict = field(default_factory=dict)
    ic_verdict: str = "unknown"
    model_status: dict = field(default_factory=dict)
    factor_summary: dict = field(default_factory=dict)


def _extract_signal_return_pairs(
    oos_result,
    test_df: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    signals = np.zeros(len(test_df))
    forward_returns = np.full(len(test_df), np.nan)

    if oos_result.kline_with_signals:
        for i, bar in enumerate(oos_result.kline_with_signals):
            if i >= len(test_df):
                break
            action = bar.get("action", "") or bar.get("s", "")
            if action == "buy":
                signals[i] = 1.0
            elif action == "sell":
                signals[i] = -1.0

    close_col = "close" if "close" in test_df.columns else test_df.columns[3] if len(test_df.columns) > 3 else None
    if close_col is None:
        return np.array([]), np.array([])

    closes = pd.to_numeric(test_df[close_col], errors="coerce").dropna().values.astype(float)
    for i in range(len(closes) - 1):
        if closes[i] > 1e-9:
            forward_returns[i] = (closes[i + 1] - closes[i]) / closes[i]

    valid = np.isfinite(forward_returns)
    return signals[valid], forward_returns[valid]


def walk_forward_ic_validation(
    strategy_cls,
    df: pd.DataFrame,
    train_days: int = 252,
    test_days: int = 63,
    initial_capital: float = 1000000,
    param_grid: dict | None = None,
    ic_lookback: int = 60,
    ic_threshold: float = 0.03,
    rank_ic_warning: float = 0.02,
    rank_ic_critical: float = 0.0,
) -> WalkForwardICResult:
    if df is None or len(df) < train_days + test_days:
        return WalkForwardICResult(
            base_result={"error": "数据不足", "windows": [], "oos_sharpe": 0, "is_sharpe": 0}
        )

    base = walk_forward_oos_validation(
        strategy_cls=strategy_cls,
        df=df,
        train_days=train_days,
        test_days=test_days,
        initial_capital=initial_capital,
        param_grid=param_grid,
    )

    if "error" in base and not base.get("windows"):
        return WalkForwardICResult(base_result=base)

    factor_monitor = FactorValidityMonitor(lookback=ic_lookback, ic_threshold=ic_threshold)
    model_monitor = ModelValidityMonitor(
        lookback=ic_lookback,
        warning_threshold=rank_ic_warning,
        critical_threshold=rank_ic_critical,
    )

    strategy_name = strategy_cls.__name__
    min_bars = _get_strategy_min_bars(strategy_name)
    n = len(df)
    ic_windows: list[ICWindowResult] = []

    window_idx = 0
    start = 0
    base_window_map: dict[int, dict] = {}
    for w in base.get("windows", []):
        base_window_map[w.get("window", window_idx)] = w

    while start + train_days + test_days <= n:
        train_end = start + train_days
        test_end = min(train_end + test_days, n)

        train_df = df.iloc[start:train_end].copy()
        test_df = df.iloc[train_end:test_end].copy()

        if len(train_df) < min_bars or len(test_df) < 10:
            start += test_days
            continue

        base_w = base_window_map.get(window_idx)
        if base_w is None:
            start += test_days
            window_idx += 1
            continue
        best_params = base_w.get("best_params", {})
        oos_sharpe = base_w.get("oos_sharpe", 0)

        if oos_sharpe == 0 and base_w.get("oos_return", 0) == 0:
            start += test_days
            window_idx += 1
            continue

        try:
            engine = BacktestEngine(initial_capital=initial_capital)
            oos_result = engine.run(strategy_cls(**best_params), test_df)
        except (InsufficientDataError, Exception) as e:
            logger.warning("IC validation OOS window %d failed: %s", window_idx, e)
            start += test_days
            window_idx += 1
            continue

        pred_scores, actual_rets = _extract_signal_return_pairs(oos_result, test_df)

        if len(pred_scores) >= 10:
            for score, ret in zip(pred_scores, actual_rets, strict=True):
                factor_monitor.update(strategy_name, float(score), float(ret))

            date_str = ""
            if "date" in test_df.columns:
                date_str = str(test_df["date"].iloc[0])[:10]

            rank_ic = model_monitor.update_rank_ic(
                model_name=strategy_name,
                date=date_str,
                predicted_ranks=pred_scores,
                actual_returns=actual_rets,
            )

            ic_val = factor_monitor.get_ic_mean(strategy_name)
            ic_ir = factor_monitor.get_ic_ir(strategy_name)
            is_valid = factor_monitor.is_valid(strategy_name)
            weight_adj = factor_monitor.get_weight_adjustment(strategy_name)
            pos_scale = model_monitor.get_position_scale(strategy_name)

            ic_windows.append(ICWindowResult(
                window=window_idx,
                ic=round(ic_val, 4),
                rank_ic=round(rank_ic, 4),
                ic_ir=round(ic_ir, 4),
                n_observations=len(pred_scores),
                factor_valid=is_valid,
                weight_adjustment=round(weight_adj, 4),
                position_scale=round(pos_scale, 4),
            ))

        window_idx += 1
        start += test_days

    ic_summary = _compute_ic_summary(ic_windows)
    ic_verdict = _determine_ic_verdict(ic_summary, base)
    model_status = model_monitor.get_status(strategy_name)
    factor_summary = factor_monitor.summary()

    return WalkForwardICResult(
        base_result=base,
        ic_windows=ic_windows,
        ic_summary=ic_summary,
        ic_verdict=ic_verdict,
        model_status=model_status,
        factor_summary=factor_summary,
    )


def _compute_ic_summary(ic_windows: list[ICWindowResult]) -> dict:
    if not ic_windows:
        return {"mean_ic": 0.0, "mean_rank_ic": 0.0, "ic_ir": 0.0, "decay_rate": 0.0, "valid_windows": 0, "total_windows": 0}

    ics = np.array([w.ic for w in ic_windows])
    rank_ics = np.array([w.rank_ic for w in ic_windows])

    mean_ic = float(np.mean(ics))
    mean_rank_ic = float(np.mean(rank_ics))
    ic_ir = mean_ic / float(np.std(ics)) if np.std(ics) > 1e-12 else 0.0

    decay_rate = 0.0
    if len(ics) >= 4:
        half = len(ics) // 2
        first_half = float(np.mean(ics[:half]))
        second_half = float(np.mean(ics[half:]))
        decay_rate = second_half - first_half

    valid_count = sum(1 for w in ic_windows if w.factor_valid)

    return {
        "mean_ic": round(mean_ic, 4),
        "mean_rank_ic": round(mean_rank_ic, 4),
        "ic_ir": round(ic_ir, 4),
        "decay_rate": round(decay_rate, 4),
        "valid_windows": valid_count,
        "total_windows": len(ic_windows),
        "validity_rate": round(valid_count / len(ic_windows), 4),
    }


def _determine_ic_verdict(ic_summary: dict, base_result: dict) -> str:
    if ic_summary.get("total_windows", 0) == 0:
        return "insufficient_data"

    mean_ic = abs(ic_summary.get("mean_ic", 0))
    decay = ic_summary.get("decay_rate", 0)
    validity = ic_summary.get("validity_rate", 0)
    base_verdict = base_result.get("verdict", "overfit")

    if mean_ic < 0.01 and decay < -0.02:
        return "strategy_degrading"

    if decay < -0.05:
        return "ic_decaying"

    if validity < 0.3:
        return "factor_invalid"

    if base_verdict == "robust" and mean_ic > 0.03 and validity > 0.6:
        return "robust"

    if base_verdict == "moderate" and mean_ic > 0.02:
        return "moderate"

    if base_verdict == "overfit":
        return "overfit"

    return "marginal"


def walk_forward_oos_validation(
    strategy_cls,
    df: pd.DataFrame,
    train_days: int = 252,
    test_days: int = 63,
    initial_capital: float = 1000000,
    param_grid: dict | None = None,
) -> dict:
    """Walk-Forward Out-of-Sample验证引擎"""
    if df is None or len(df) < train_days + test_days:
        return {"error": "数据不足", "windows": [], "oos_sharpe": 0, "is_sharpe": 0}

    min_bars = _get_strategy_min_bars(strategy_cls.__name__)
    n = len(df)
    windows = []
    oos_sharpes = []
    is_sharpes = []
    oos_returns = []
    is_returns = []
    best_params_list = []

    window_idx = 0
    start = 0
    while start + train_days + test_days <= n:
        train_end = start + train_days
        test_end = min(train_end + test_days, n)

        train_df = df.iloc[start:train_end].copy()
        test_df = df.iloc[train_end:test_end].copy()

        if len(train_df) < min_bars or len(test_df) < 10:
            start += test_days
            continue

        best_sharpe = -np.inf
        best_params = {}
        best_is_result = None

        if param_grid:
            from itertools import product
            keys = list(param_grid.keys())
            values = list(param_grid.values())
            for combo in product(*values):
                params = dict(zip(keys, combo, strict=True))
                try:
                    engine = BacktestEngine(initial_capital=initial_capital)
                    result = engine.run(strategy_cls(**params), train_df)
                    if result.sharpe_ratio > best_sharpe:
                        best_sharpe = result.sharpe_ratio
                        best_params = params
                        best_is_result = result
                except (InsufficientDataError, Exception) as e:
                    logger.warning("IS window %d param combo failed: %s", window_idx, e)
        else:
            try:
                engine = BacktestEngine(initial_capital=initial_capital)
                result = engine.run(strategy_cls(), train_df)
                best_sharpe = result.sharpe_ratio
                best_params = {}
                best_is_result = result
            except (InsufficientDataError, Exception) as e:
                logger.warning("IS window %d default params failed: %s", window_idx, e)
                start += test_days
                continue

        if best_is_result is None:
            start += test_days
            continue

        is_sharpes.append(best_sharpe)
        is_returns.append(best_is_result.total_return)

        try:
            engine = BacktestEngine(initial_capital=initial_capital)
            oos_result = engine.run(strategy_cls(**best_params), test_df)
            oos_sharpes.append(oos_result.sharpe_ratio)
            oos_returns.append(oos_result.total_return)
        except (InsufficientDataError, Exception) as e:
            logger.warning("OOS window %d failed: %s", window_idx, e)
            oos_sharpes.append(0.0)
            oos_returns.append(0.0)

        best_params_list.append(best_params)
        windows.append({
            "window": window_idx,
            "train_start": str(train_df["date"].iloc[0])[:10] if "date" in train_df.columns else "",
            "train_end": str(train_df["date"].iloc[-1])[:10] if "date" in train_df.columns else "",
            "test_start": str(test_df["date"].iloc[0])[:10] if "date" in test_df.columns else "",
            "test_end": str(test_df["date"].iloc[-1])[:10] if "date" in test_df.columns else "",
            "is_sharpe": round(best_sharpe, 2),
            "oos_sharpe": round(oos_sharpes[-1], 2),
            "is_return": round(is_returns[-1], 2),
            "oos_return": round(oos_returns[-1], 2),
            "best_params": best_params,
        })

        window_idx += 1
        start += test_days

    if not windows:
        return {"error": "无法生成有效验证窗口", "windows": [], "oos_sharpe": 0, "is_sharpe": 0}

    avg_oos_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
    avg_is_sharpe = float(np.mean(is_sharpes)) if is_sharpes else 0.0
    avg_oos_return = float(np.mean(oos_returns)) if oos_returns else 0.0
    avg_is_return = float(np.mean(is_returns)) if is_returns else 0.0

    overfitting_ratio = 0.0
    if abs(avg_is_sharpe) > 1e-9:
        overfitting_ratio = max(0, 1 - avg_oos_sharpe / avg_is_sharpe)

    consistency = 0.0
    if oos_sharpes:
        positive_count = sum(1 for s in oos_sharpes if s > 0)
        consistency = positive_count / len(oos_sharpes)

    param_stability = {}
    if best_params_list:
        for key in best_params_list[0]:
            vals = [p.get(key) for p in best_params_list if key in p]
            if vals and all(isinstance(v, (int, float)) for v in vals):
                param_stability[key] = {
                    "mean": round(float(np.mean(vals)), 2),
                    "std": round(float(np.std(vals)), 2),
                    "min": round(float(np.min(vals)), 2),
                    "max": round(float(np.max(vals)), 2),
                }

    return {
        "windows": windows,
        "summary": {
            "avg_is_sharpe": round(avg_is_sharpe, 4),
            "avg_oos_sharpe": round(avg_oos_sharpe, 4),
            "avg_is_return": round(avg_is_return, 4),
            "avg_oos_return": round(avg_oos_return, 4),
            "overfitting_ratio": round(overfitting_ratio, 4),
            "consistency_rate": round(consistency, 4),
            "n_windows": len(windows),
        },
        "param_stability": param_stability,
        "verdict": (
            "robust" if overfitting_ratio < 0.3 and consistency > 0.6 else
            "moderate" if overfitting_ratio < 0.5 and consistency > 0.4 else
            "overfit"
        ),
    }
