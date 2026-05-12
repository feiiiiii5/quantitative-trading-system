import logging
from concurrent.futures import ThreadPoolExecutor
from itertools import product as _itertools_product

import numpy as np
import pandas as pd

from .result import BacktestResult, InsufficientDataError

logger = logging.getLogger(__name__)


def monte_carlo_analysis(engine, result: BacktestResult, n_simulations: int = 1000) -> dict:
    sell_trades = [t for t in result.trades if t.get("action") == "sell"]
    if not sell_trades:
        return {"error": "交易样本不足，无法进行蒙特卡洛分析"}

    pnl = np.array([float(t.get("pnl", 0)) for t in sell_trades], dtype=float)
    if len(pnl) < 2:
        return {"error": "交易样本不足，无法进行蒙特卡洛分析"}

    rng = np.random.default_rng(42)
    n_sim = max(1, int(n_simulations))
    n_sample_paths = min(30, n_sim)
    sample_indices = set(rng.choice(n_sim, size=n_sample_paths, replace=False))

    finals = []
    max_dds = []
    sharpes = []
    paths = []
    initial_capital = engine._initial_capital
    for sim_idx in range(n_sim):
        sampled = rng.choice(pnl, size=len(pnl), replace=True)
        curve = initial_capital + np.cumsum(sampled)
        peak = np.maximum.accumulate(curve)
        dd = np.where(peak > 1e-9, (peak - curve) / peak * 100, 0)
        finals.append(float(curve[-1]))
        max_dds.append(float(np.max(dd)))
        trade_ret = sampled / max(initial_capital, 1)
        std = np.std(trade_ret)
        sharpes.append(float(np.mean(trade_ret) / std) if std > 1e-12 else 0.0)
        if sim_idx in sample_indices:
            paths.append((curve / initial_capital).tolist())

    final_arr = np.array(finals)
    dd_arr = np.array(max_dds)
    sharpe_arr = np.array(sharpes)
    sim_sharpe_median = float(np.median(sharpe_arr)) if len(sharpe_arr) else 0.0
    robustness = result.sharpe_ratio / sim_sharpe_median if abs(sim_sharpe_median) > 1e-9 else 0.0
    initial = max(initial_capital, 1)
    median_final = float(np.percentile(final_arr, 50))
    p5_final = float(np.percentile(final_arr, 5))
    p95_final = float(np.percentile(final_arr, 95))
    ruin_count = int(np.sum(final_arr < initial * 0.5))
    mc_result = {
        "paths": paths,
        "median_return": round((median_final - initial) / initial, 4),
        "p5_return": round((p5_final - initial) / initial, 4),
        "p95_return": round((p95_final - initial) / initial, 4),
        "ruin_prob": round(ruin_count / max(n_sim, 1), 4),
        "final_equity_p5": round(p5_final, 2),
        "final_equity_p50": round(median_final, 2),
        "final_equity_p95": round(p95_final, 2),
        "max_drawdown_p5": round(float(np.percentile(dd_arr, 5)), 2),
        "max_drawdown_p50": round(float(np.percentile(dd_arr, 50)), 2),
        "max_drawdown_p95": round(float(np.percentile(dd_arr, 95)), 2),
        "sharpe_p50": round(sim_sharpe_median, 2),
        "robustness_score": round(float(robustness), 2),
    }
    result.monte_carlo = mc_result
    return mc_result


def sensitivity_analysis(engine, strategy_cls, df: pd.DataFrame,
                         base_params: dict, param_ranges: dict | None = None) -> dict:
    base_params = base_params or {}
    param_ranges = param_ranges or strategy_cls.get_param_space()
    if not param_ranges or df is None or df.empty:
        return {"parameters": {}, "heatmap": [], "recommendation": {}}

    output = {}
    for name, spec in param_ranges.items():
        base_val = base_params.get(name, (spec.get("min", 0) + spec.get("max", 0)) / 2)
        if not isinstance(base_val, (int, float)):
            continue
        low = max(spec.get("min", base_val * 0.8), base_val * 0.8)
        high = min(spec.get("max", base_val * 1.2), base_val * 1.2)
        values = np.linspace(low, high, 5)
        points = []
        sharpes = []
        for value in values:
            params = dict(base_params)
            params[name] = int(round(value)) if isinstance(base_val, int) else round(float(value), 4)
            try:
                result = engine.run(strategy_cls(**params), df)
                sharpe = float(result.sharpe_ratio)
            except Exception as e:
                logger.debug("Param scan iteration failed: %s", e)
                sharpe = 0.0
            sharpes.append(sharpe)
            points.append({"value": params[name], "sharpe_ratio": round(sharpe, 4)})
        param_range = high - low
        elasticity = (max(sharpes) - min(sharpes)) / param_range if sharpes and param_range > 1e-9 else 0.0
        output[name] = {"points": points, "elasticity": round(float(elasticity), 6)}

    heatmap = []
    names = list(output.keys())[:2]
    if len(names) == 2:
        x_name, y_name = names
        x_values = [p["value"] for p in output[x_name]["points"]]
        y_values = [p["value"] for p in output[y_name]["points"]]
        for xv in x_values:
            for yv in y_values:
                params = dict(base_params)
                params[x_name] = xv
                params[y_name] = yv
                try:
                    result = engine.run(strategy_cls(**params), df)
                    sharpe = float(result.sharpe_ratio)
                except Exception as e:
                    logger.debug("Heatmap scan iteration failed: %s", e)
                    sharpe = 0.0
                heatmap.append({"x": xv, "y": yv, "sharpe_ratio": round(sharpe, 4)})

    recommendation = {}
    for name, data in output.items():
        pts = data.get("points", [])
        if pts:
            best = max(pts, key=lambda x: x["sharpe_ratio"])
            recommendation[name] = best["value"]
    return {"parameters": output, "heatmap": heatmap, "recommendation": recommendation}


def parameter_grid_scan(
    engine,
    strategy_cls,
    df: pd.DataFrame,
    param_x: str,
    param_y: str,
    x_range: tuple | None = None,
    y_range: tuple | None = None,
    grid_size: int = 7,
    base_params: dict | None = None,
    metric: str = "sharpe_ratio",
) -> dict:
    base_params = base_params or {}
    param_space = strategy_cls.get_param_space() if hasattr(strategy_cls, "get_param_space") else {}

    if x_range is None:
        spec = param_space.get(param_x, {})
        x_min = spec.get("min", 5)
        x_max = spec.get("max", 60)
        x_range = (x_min, x_max)
    if y_range is None:
        spec = param_space.get(param_y, {})
        y_min = spec.get("min", 5)
        y_max = spec.get("max", 60)
        y_range = (y_min, y_max)

    x_base = base_params.get(param_x, (x_range[0] + x_range[1]) / 2)
    y_base = base_params.get(param_y, (y_range[0] + y_range[1]) / 2)
    x_is_int = isinstance(x_base, int)
    y_is_int = isinstance(y_base, int)

    x_values = np.linspace(x_range[0], x_range[1], grid_size)
    y_values = np.linspace(y_range[0], y_range[1], grid_size)
    if x_is_int:
        x_values = np.unique(np.round(x_values).astype(int))
    if y_is_int:
        y_values = np.unique(np.round(y_values).astype(int))

    grid_cells = []
    for xv in x_values:
        for yv in y_values:
            params = dict(base_params)
            params[param_x] = int(round(xv)) if x_is_int else round(float(xv), 4)
            params[param_y] = int(round(yv)) if y_is_int else round(float(yv), 4)
            grid_cells.append((params, param_x, param_y, x_is_int, y_is_int))

    n_workers = min(len(grid_cells), 8)
    heatmap = []

    def _scan_cell(cell: tuple) -> dict:
        params, px, py, xi, yi = cell
        try:
            result = engine.run(strategy_cls(**params), df)
            val = getattr(result, metric, 0.0)
            if not np.isfinite(val):
                val = 0.0
            return {
                "x": params[px],
                "y": params[py],
                metric: round(float(val), 4),
                "total_return": round(float(result.total_return), 4),
                "max_drawdown": round(float(result.max_drawdown), 4),
                "_val": val,
            }
        except InsufficientDataError:
            logger.debug(
                "Grid scan (%s=%s, %s=%s) skipped: insufficient data",
                px, params[px], py, params[py],
            )
            return {
                "x": params[px], "y": params[py],
                metric: 0.0, "total_return": 0, "max_drawdown": 0, "_val": 0.0,
            }
        except Exception as e:
            logger.debug(
                "Grid scan (%s=%s, %s=%s) failed: %s",
                px, params[px], py, params[py], e,
            )
            return {
                "x": params[px], "y": params[py],
                metric: 0.0, "total_return": 0, "max_drawdown": 0, "_val": 0.0,
            }

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        for cell_result in pool.map(_scan_cell, grid_cells):
            clean_result = {k: v for k, v in cell_result.items() if k != "_val"}
            heatmap.append(clean_result)

    best_sharpe = -np.inf
    best_params = {}
    for cell_result in heatmap:
        val = cell_result[metric]
        if val > best_sharpe:
            best_sharpe = val
            best_params = {param_x: cell_result["x"], param_y: cell_result["y"]}

    return {
        "param_x": param_x,
        "param_y": param_y,
        "x_values": [int(v) if x_is_int else round(float(v), 2) for v in x_values],
        "y_values": [int(v) if y_is_int else round(float(v), 2) for v in y_values],
        "metric": metric,
        "heatmap": heatmap,
        "best_params": best_params,
        "best_value": round(float(best_sharpe), 4),
    }


def parameter_sensitivity(
    engine,
    strategy_cls,
    df: pd.DataFrame,
    param_name: str,
    param_range: tuple | None = None,
    num_points: int = 11,
    base_params: dict | None = None,
    metrics: tuple[str, ...] = ("sharpe_ratio", "total_return", "max_drawdown", "win_rate"),
) -> dict:
    base_params = base_params or {}
    param_space = strategy_cls.get_param_space() if hasattr(strategy_cls, "get_param_space") else {}

    if param_range is None:
        spec = param_space.get(param_name, {})
        p_min = spec.get("min", 5)
        p_max = spec.get("max", 60)
        param_range = (p_min, p_max)

    p_base = base_params.get(param_name, (param_range[0] + param_range[1]) / 2)
    is_int = isinstance(p_base, int)

    values = np.linspace(param_range[0], param_range[1], num_points)
    if is_int:
        values = np.unique(np.round(values).astype(int))

    results = []
    for v in values:
        params = dict(base_params)
        params[param_name] = int(round(v)) if is_int else round(float(v), 4)
        try:
            r = engine.run(strategy_cls(**params), df)
            entry = {"value": params[param_name]}
            for m in metrics:
                val = getattr(r, m, 0.0)
                entry[m] = round(float(val), 4) if val is not None and np.isfinite(val) else 0.0
            results.append(entry)
        except Exception as e:
            logger.debug("Sensitivity scan (%s=%s) failed: %s", param_name, params[param_name], e)
            entry = {"value": params[param_name]}
            for m in metrics:
                entry[m] = 0.0
            results.append(entry)

    if len(results) < 2:
        return {"param_name": param_name, "results": results, "sensitivity": {}, "robustness": {}}

    sensitivity = {}
    robustness = {}
    for m in metrics:
        vals = [r[m] for r in results]
        best_idx = max(range(len(vals)), key=lambda i: vals[i] if m != "max_drawdown" else -vals[i])
        best_val = vals[best_idx]

        deltas = [abs(vals[i + 1] - vals[i]) for i in range(len(vals) - 1)]
        avg_delta = sum(deltas) / len(deltas) if deltas else 0.0
        param_span = values[-1] - values[0] if len(values) > 1 else 1.0
        param_span = max(param_span, 1e-9)
        sensitivity[m] = round(avg_delta / param_span, 6)

        if best_val != 0:
            degradations = [abs(v - best_val) / abs(best_val) for v in vals]
            robustness[m] = round(1.0 - max(degradations), 4)
        else:
            robustness[m] = 0.0

    return {
        "param_name": param_name,
        "param_range": [float(param_range[0]), float(param_range[1])],
        "results": results,
        "sensitivity": sensitivity,
        "robustness": robustness,
    }


def walk_forward_analysis(
    engine,
    strategy_cls,
    df: pd.DataFrame,
    is_window: int = 252,
    oos_window: int = 63,
    anchored: bool = False,
    metric: str = "sharpe_ratio",
    base_params: dict | None = None,
    param_ranges: dict | None = None,
) -> dict:
    if df is None or len(df) < is_window + oos_window:
        return {"error": f"数据不足，至少需要{is_window + oos_window}根K线"}

    base_params = base_params or {}
    param_ranges = param_ranges or (strategy_cls.get_param_space() if hasattr(strategy_cls, "get_param_space") else {})

    if not param_ranges:
        results = []
        step = oos_window
        for start in range(0, len(df) - is_window - oos_window + 1, step):
            is_end = start + is_window
            oos_end = min(is_end + oos_window, len(df))
            if oos_end <= is_end:
                break
            is_df = df.iloc[start:is_end]
            oos_df = df.iloc[is_end:oos_end]
            try:
                is_result = engine.run(strategy_cls(**base_params), is_df)
                oos_result = engine.run(strategy_cls(**base_params), oos_df)
                results.append({
                    "is_start": int(start),
                    "is_end": int(is_end),
                    "oos_end": int(oos_end),
                    "is_sharpe": round(float(is_result.sharpe_ratio), 4),
                    "oos_sharpe": round(float(oos_result.sharpe_ratio), 4),
                    "is_return": round(float(is_result.total_return), 4),
                    "oos_return": round(float(oos_result.total_return), 4),
                    "is_max_dd": round(float(is_result.max_drawdown), 4),
                    "oos_max_dd": round(float(oos_result.max_drawdown), 4),
                })
            except Exception as e:
                logger.debug("WFA window failed: %s", e)
        if not results:
            return {"error": "所有窗口回测失败"}
        is_sharpes = [r["is_sharpe"] for r in results]
        oos_sharpes = [r["oos_sharpe"] for r in results]
        median_is = float(np.median(is_sharpes))
        median_oos = float(np.median(oos_sharpes))
        wfa_efficiency = median_oos / median_is if abs(median_is) > 1e-9 else 0.0
        profitable_oos = sum(1 for s in oos_sharpes if s > 0)
        return {
            "windows": results,
            "n_windows": len(results),
            "is_median_sharpe": round(median_is, 4),
            "oos_median_sharpe": round(median_oos, 4),
            "wfa_efficiency": round(wfa_efficiency, 4),
            "oos_profitable_pct": round(profitable_oos / max(len(results), 1) * 100, 1),
            "is_oos_ratio": f"{is_window}:{oos_window}",
            "curve_fitted": wfa_efficiency < 0.3,
        }

    results = []
    step = oos_window
    for start in range(0, len(df) - is_window - oos_window + 1, step):
        is_start = 0 if anchored else start
        is_end = start + is_window
        oos_end = min(is_end + oos_window, len(df))
        if oos_end <= is_end:
            break
        is_df = df.iloc[is_start:is_end]
        oos_df = df.iloc[is_end:oos_end]

        best_params = dict(base_params)
        best_sharpe = -np.inf
        param_names = list(param_ranges.keys())[:3]
        if param_names:
            grid_values = []
            for name in param_names:
                spec = param_ranges[name]
                p_min = spec.get("min", 5)
                p_max = spec.get("max", 60)
                grid_values.append(np.linspace(p_min, p_max, 5).tolist())
            for combo in _itertools_product(*grid_values):
                params = dict(base_params)
                for i, name in enumerate(param_names):
                    base_val = base_params.get(name, 10)
                    params[name] = int(round(combo[i])) if isinstance(base_val, int) else round(float(combo[i]), 4)
                try:
                    r = engine.run(strategy_cls(**params), is_df)
                    val = getattr(r, metric, 0.0)
                    if val > best_sharpe:
                        best_sharpe = val
                        best_params = params
                except Exception as e:
                    logger.debug("Parameter combo failed: %s", e)
                    continue

        try:
            oos_result = engine.run(strategy_cls(**best_params), oos_df)
            is_result = engine.run(strategy_cls(**best_params), is_df)
            results.append({
                "is_start": int(is_start),
                "is_end": int(is_end),
                "oos_end": int(oos_end),
                "best_params": {k: v for k, v in best_params.items() if k in param_names},
                "is_sharpe": round(float(is_result.sharpe_ratio), 4),
                "oos_sharpe": round(float(oos_result.sharpe_ratio), 4),
                "is_return": round(float(is_result.total_return), 4),
                "oos_return": round(float(oos_result.total_return), 4),
                "oos_max_dd": round(float(oos_result.max_drawdown), 4),
            })
        except Exception as e:
            logger.debug("WFA optimized window failed: %s", e)

    if not results:
        return {"error": "所有窗口回测失败"}

    is_sharpes = [r["is_sharpe"] for r in results]
    oos_sharpes = [r["oos_sharpe"] for r in results]
    median_is = float(np.median(is_sharpes))
    median_oos = float(np.median(oos_sharpes))
    wfa_efficiency = median_oos / median_is if abs(median_is) > 1e-9 else 0.0
    profitable_oos = sum(1 for s in oos_sharpes if s > 0)

    return {
        "windows": results,
        "n_windows": len(results),
        "is_median_sharpe": round(median_is, 4),
        "oos_median_sharpe": round(median_oos, 4),
        "wfa_efficiency": round(wfa_efficiency, 4),
        "oos_profitable_pct": round(profitable_oos / max(len(results), 1) * 100, 1),
        "is_oos_ratio": f"{is_window}:{oos_window}",
        "curve_fitted": wfa_efficiency < 0.3,
    }
