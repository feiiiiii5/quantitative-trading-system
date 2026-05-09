import logging
import time
from itertools import product
from typing import Any

import numpy as np
import pandas as pd

from core.backtest import BacktestEngine
from core.strategies import (
    ATRChannelBreakoutStrategy,
    BollingerBreakoutStrategy,
    DonchianChannelStrategy,
    DualMAStrategy,
    MACDStrategy,
    RSIMeanReversionStrategy,
)

logger = logging.getLogger(__name__)

_STRATEGY_PARAM_SPECS: dict[str, dict[str, dict[str, Any]]] = {
    "DualMAStrategy": {
        "short_window": {"type": "int", "min": 3, "max": 30, "step": 1, "default": 5},
        "long_window": {"type": "int", "min": 10, "max": 120, "step": 5, "default": 20},
    },
    "MACrossStrategy": {
        "short_window": {"type": "int", "min": 3, "max": 30, "step": 1, "default": 5},
        "long_window": {"type": "int", "min": 10, "max": 120, "step": 5, "default": 20},
    },
    "RSIMeanReversionStrategy": {
        "period": {"type": "int", "min": 5, "max": 30, "step": 1, "default": 14},
        "oversold": {"type": "int", "min": 15, "max": 35, "step": 1, "default": 30},
        "overbought": {"type": "int", "min": 65, "max": 90, "step": 1, "default": 70},
    },
    "BollingerBreakoutStrategy": {
        "period": {"type": "int", "min": 10, "max": 30, "step": 1, "default": 20},
        "num_std": {"type": "float", "min": 1.0, "max": 3.0, "step": 0.1, "default": 2.0},
    },
    "MACDStrategy": {
        "fast_period": {"type": "int", "min": 5, "max": 20, "step": 1, "default": 12},
        "slow_period": {"type": "int", "min": 20, "max": 40, "step": 1, "default": 26},
        "signal_period": {"type": "int", "min": 5, "max": 15, "step": 1, "default": 9},
    },
    "ATRChannelBreakoutStrategy": {
        "period": {"type": "int", "min": 10, "max": 30, "step": 1, "default": 20},
        "multiplier": {"type": "float", "min": 1.0, "max": 3.0, "step": 0.1, "default": 2.0},
    },
    "DonchianChannelStrategy": {
        "period": {"type": "int", "min": 10, "max": 60, "step": 5, "default": 20},
    },
}

_STRATEGY_CLASSES = {
    "DualMAStrategy": DualMAStrategy,
    "MACrossStrategy": DualMAStrategy,
    "RSIMeanReversionStrategy": RSIMeanReversionStrategy,
    "BollingerBreakoutStrategy": BollingerBreakoutStrategy,
    "MACDStrategy": MACDStrategy,
    "ATRChannelBreakoutStrategy": ATRChannelBreakoutStrategy,
    "DonchianChannelStrategy": DonchianChannelStrategy,
}


def get_param_specs() -> dict:
    return _STRATEGY_PARAM_SPECS


def _make_strategy(strategy_name: str, params: dict[str, Any]) -> Any:
    cls = _STRATEGY_CLASSES.get(strategy_name)
    if cls is None:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    return cls(**params)


def _generate_grid(spec: dict[str, dict[str, Any]], max_combos: int = 200) -> list[dict[str, Any]]:
    param_ranges: dict[str, list] = {}
    for pname, pspec in spec.items():
        ptype = pspec["type"]
        pmin, pmax, pstep = pspec["min"], pspec["max"], pspec["step"]
        if ptype == "int":
            vals = list(range(int(pmin), int(pmax) + 1, max(1, int(pstep))))
        else:
            n_steps = max(1, int((pmax - pmin) / pstep))
            vals = [round(pmin + i * pstep, 4) for i in range(n_steps + 1)]
        param_ranges[pname] = vals

    total_combos = 1
    for vals in param_ranges.values():
        total_combos *= len(vals)
        if total_combos > 100000:
            logger.warning("Grid size exceeds 100k combinations, truncating parameter ranges")
            for k in param_ranges:
                step = max(1, len(param_ranges[k]) // 5)
                param_ranges[k] = param_ranges[k][::step]
            break

    keys = list(param_ranges.keys())
    combos = list(product(*[param_ranges[k] for k in keys]))
    if len(combos) > max_combos:
        step = max(1, len(combos) // max_combos)
        combos = combos[::step][:max_combos]

    return [dict(zip(keys, combo, strict=False)) for combo in combos]


def run_param_optimization(
    strategy_name: str,
    df: pd.DataFrame,
    metric: str = "sharpe_ratio",
    max_combos: int = 200,
    timeout_seconds: float = 30.0,
) -> dict:
    spec = _STRATEGY_PARAM_SPECS.get(strategy_name)
    if spec is None:
        raise ValueError(f"Strategy {strategy_name} not supported for optimization")

    grid = _generate_grid(spec, max_combos)
    logger.info("Parameter optimization: %s, %s combinations, metric=%s", strategy_name, len, metric)

    engine = BacktestEngine()
    results = []
    start_time = time.monotonic()

    for i, params in enumerate(grid):
        if time.monotonic() - start_time > timeout_seconds:
            logger.warning("Optimization timed out after %s combinations", i)
            break

        try:
            strategy = _make_strategy(strategy_name, params)
            bt_result = engine.run(strategy, df)
            result_entry = {
                "params": {k: (int(v) if isinstance(v, (np.integer,)) else round(float(v), 4) if isinstance(v, (np.floating, float)) else v) for k, v in params.items()},
                "total_return": round(float(bt_result.total_return), 4),
                "annual_return": round(float(bt_result.annual_return), 4),
                "sharpe_ratio": round(float(bt_result.sharpe_ratio), 4),
                "max_drawdown": round(float(bt_result.max_drawdown), 4),
                "win_rate": round(float(bt_result.win_rate), 4),
                "total_trades": int(bt_result.total_trades),
            }
            results.append(result_entry)
        except Exception as e:
            logger.debug("Optimization combo failed: %s, error: %s", params, e)
            continue

    if not results:
        return {"strategy": strategy_name, "metric": metric, "best": None, "all_results": [], "total_combos": len(grid), "completed": 0}

    sort_key = metric
    reverse = metric in ("sharpe_ratio", "total_return", "annual_return", "win_rate")
    results.sort(key=lambda x: x.get(sort_key, 0), reverse=reverse)

    best = results[0]
    top_10 = results[:10]

    return {
        "strategy": strategy_name,
        "metric": metric,
        "best": best,
        "top_results": top_10,
        "total_combos": len(grid),
        "completed": len(results),
        "elapsed_seconds": round(time.monotonic() - start_time, 2),
    }


def run_stress_test(
    df: pd.DataFrame,
    symbols: list[str] | None = None,
    scenarios: list[str] | None = None,
) -> dict:
    if df.empty or len(df) < 30:
        return {"error": "Insufficient data for stress testing"}

    close = df["close"] if "close" in df.columns else df.iloc[:, -1]
    returns = close.pct_change().dropna()
    if returns.empty:
        return {"error": "No returns data available"}

    current_price = float(close.iloc[-1])
    current_vol = float(returns.std() * np.sqrt(252))
    current_mean = float(returns.mean() * 252)

    default_scenarios = {
        "market_crash": {
            "description": "市场崩盘 (-20%)",
            "shock": -0.20,
            "vol_multiplier": 2.5,
        },
        "vol_spike": {
            "description": "波动率飙升 (+40%)",
            "shock": -0.05,
            "vol_multiplier": 3.0,
        },
        "flash_crash": {
            "description": "闪崩 (-10% 瞬时)",
            "shock": -0.10,
            "vol_multiplier": 5.0,
        },
        "slow_grind": {
            "description": "缓慢阴跌 (-5%/月, 持续6月)",
            "shock": -0.26,
            "vol_multiplier": 1.5,
        },
        "rate_hike": {
            "description": "加息冲击 (-8%)",
            "shock": -0.08,
            "vol_multiplier": 2.0,
        },
        "correlation_collapse": {
            "description": "相关性崩溃",
            "shock": -0.15,
            "vol_multiplier": 2.5,
        },
    }

    active_scenarios = default_scenarios
    if scenarios:
        active_scenarios = {k: v for k, v in default_scenarios.items() if k in scenarios}

    results = {}
    for name, scenario in active_scenarios.items():
        shocked_price = current_price * (1 + scenario["shock"])
        shocked_vol = current_vol * scenario["vol_multiplier"]

        n_sim = 1000
        horizon = 20
        daily_vol = shocked_vol / np.sqrt(252)
        daily_drift = (current_mean + scenario["shock"]) / 252

        sim_returns = np.random.normal(daily_drift, daily_vol, (n_sim, horizon))
        sim_prices = current_price * np.cumprod(1 + sim_returns, axis=1)

        final_prices = sim_prices[:, -1]
        p5 = float(np.percentile(final_prices, 5))
        p25 = float(np.percentile(final_prices, 25))
        p50 = float(np.percentile(final_prices, 50))
        p75 = float(np.percentile(final_prices, 75))
        p95 = float(np.percentile(final_prices, 95))

        max_loss = float(np.min(final_prices) / current_price - 1)
        avg_loss = float(np.mean(final_prices) / current_price - 1)

        results[name] = {
            "description": scenario["description"],
            "shocked_price": round(shocked_price, 2),
            "shocked_volatility": round(shocked_vol, 4),
            "p5": round(p5, 2),
            "p25": round(p25, 2),
            "p50": round(p50, 2),
            "p75": round(p75, 2),
            "p95": round(p95, 2),
            "max_loss_pct": round(max_loss * 100, 2),
            "avg_loss_pct": round(avg_loss * 100, 2),
            "recovery_probability": round(float(np.mean(final_prices >= current_price * 0.95)), 4),
        }

    return {
        "current_price": round(current_price, 2),
        "current_volatility": round(current_vol, 4),
        "scenarios": results,
    }


def run_bayesian_optimization(
    strategy_name: str,
    df: pd.DataFrame,
    metric: str = "sharpe_ratio",
    n_trials: int = 50,
    timeout_seconds: float = 60.0,
) -> dict:
    try:
        return _run_optuna_optimization(strategy_name, df, metric, n_trials, timeout_seconds)
    except ImportError:
        logger.debug("Optuna not available, falling back to scipy differential_evolution")
        return _run_scipy_optimization(strategy_name, df, metric, n_trials, timeout_seconds)


def _run_optuna_optimization(
    strategy_name: str,
    df: pd.DataFrame,
    metric: str = "sharpe_ratio",
    n_trials: int = 50,
    timeout_seconds: float = 60.0,
) -> dict:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    spec = _STRATEGY_PARAM_SPECS.get(strategy_name)
    if spec is None:
        raise ValueError(f"Strategy {strategy_name} not supported for optimization")

    engine = BacktestEngine()
    start_time = time.monotonic()
    evaluated_params: list[dict] = []

    maximize = metric in ("sharpe_ratio", "total_return", "annual_return", "win_rate")
    direction = "maximize" if maximize else "minimize"

    def objective(trial: optuna.Trial) -> float:
        if time.monotonic() - start_time > timeout_seconds:
            raise optuna.TrialPruned()

        params = {}
        for pname, pspec in spec.items():
            if pspec["type"] == "int":
                params[pname] = trial.suggest_int(pname, int(pspec["min"]), int(pspec["max"]))
            else:
                params[pname] = trial.suggest_float(pname, float(pspec["min"]), float(pspec["max"]), step=float(pspec.get("step", 0.1)))

        try:
            strategy = _make_strategy(strategy_name, params)
            bt_result = engine.run(strategy, df)
            score = float(getattr(bt_result, metric, 0))
            evaluated_params.append({
                "params": {k: (int(v) if isinstance(v, (np.integer,)) else round(float(v), 4) if isinstance(v, (np.floating, float)) else v) for k, v in params.items()},
                metric: round(score, 4),
                "total_return": round(float(bt_result.total_return), 4),
                "sharpe_ratio": round(float(bt_result.sharpe_ratio), 4),
            })
            return score
        except Exception as e:
            logger.debug("Optuna trial failed: %s", e)
            raise optuna.TrialPruned()

    sampler = optuna.samplers.TPESampler(seed=42)
    study = optuna.create_study(direction=direction, sampler=sampler)
    study.optimize(objective, n_trials=n_trials, timeout=timeout_seconds, show_progress_bar=False)

    if evaluated_params:
        evaluated_params.sort(key=lambda x: x.get(metric, 0), reverse=maximize)
        best = evaluated_params[0]
    else:
        best = {"params": dict(study.best_params), metric: round(study.best_value, 4)}

    return {
        "strategy": strategy_name,
        "metric": metric,
        "best": best,
        "top_results": evaluated_params[:10],
        "optimization_method": "optuna_tpe",
        "n_trials": len(evaluated_params),
        "elapsed_seconds": round(time.monotonic() - start_time, 2),
    }


def _run_scipy_optimization(
    strategy_name: str,
    df: pd.DataFrame,
    metric: str = "sharpe_ratio",
    n_trials: int = 50,
    timeout_seconds: float = 60.0,
) -> dict:
    from scipy.optimize import differential_evolution

    spec = _STRATEGY_PARAM_SPECS.get(strategy_name)
    if spec is None:
        raise ValueError(f"Strategy {strategy_name} not supported for optimization")

    bounds = []
    param_names = []
    for pname, pspec in spec.items():
        param_names.append(pname)
        bounds.append((pspec["min"], pspec["max"]))

    engine = BacktestEngine()
    start_time = time.monotonic()
    evaluated_params = []

    def objective(x):
        if time.monotonic() - start_time > timeout_seconds:
            return 1e6
        params = {}
        for i, pname in enumerate(param_names):
            pspec = spec[pname]
            if pspec["type"] == "int":
                params[pname] = int(round(x[i]))
            else:
                params[pname] = round(x[i], 4)

        try:
            strategy = _make_strategy(strategy_name, params)
            bt_result = engine.run(strategy, df)
            score = float(getattr(bt_result, metric, 0))
            evaluated_params.append({
                "params": params,
                metric: round(score, 4),
                "total_return": round(float(bt_result.total_return), 4),
                "sharpe_ratio": round(float(bt_result.sharpe_ratio), 4),
            })
            return -score if metric in ("sharpe_ratio", "total_return", "annual_return", "win_rate") else score
        except Exception as e:
            logger.debug("优化目标函数失败: %s", e)
            return 1e6

    result = differential_evolution(
        objective,
        bounds,
        maxiter=n_trials,
        seed=42,
        polish=True,
        workers=1,
    )

    best_params = {}
    for i, pname in enumerate(param_names):
        pspec = spec[pname]
        if pspec["type"] == "int":
            best_params[pname] = int(round(result.x[i]))
        else:
            best_params[pname] = round(result.x[i], 4)

    if evaluated_params:
        sort_key = metric
        reverse = metric in ("sharpe_ratio", "total_return", "annual_return", "win_rate")
        evaluated_params.sort(key=lambda x: x.get(sort_key, 0), reverse=reverse)
        best = evaluated_params[0]
    else:
        best = {"params": best_params, metric: -result.fun if result.fun < 1e5 else 0}

    return {
        "strategy": strategy_name,
        "metric": metric,
        "best": best,
        "top_results": evaluated_params[:10],
        "optimization_method": "differential_evolution",
        "n_trials": len(evaluated_params),
        "elapsed_seconds": round(time.monotonic() - start_time, 2),
    }
