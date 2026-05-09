import logging

import numpy as np

logger = logging.getLogger(__name__)


class BacktestProfiler:
    """Profiles backtest performance and identifies bottlenecks."""

    def __init__(self):
        self._timings: dict[str, list[float]] = {}
        self._counts: dict[str, int] = {}

    def record(self, name: str, duration: float) -> None:
        if name not in self._timings:
            self._timings[name] = []
        self._timings[name].append(duration)
        self._counts[name] = self._counts.get(name, 0) + 1

    def get_report(self) -> dict:
        if not self._timings:
            return {"error": "No profiling data collected"}

        report = {}
        for name, times in self._timings.items():
            if not times:
                continue
            avg_ms = float(np.mean(times)) * 1000
            total_ms = float(np.sum(times)) * 1000
            report[name] = {
                "calls": self._counts.get(name, 0),
                "avg_ms": round(avg_ms, 3),
                "total_ms": round(total_ms, 3),
                "min_ms": round(float(np.min(times)) * 1000, 3),
                "max_ms": round(float(np.max(times)) * 1000, 3),
            }

        sorted_report = dict(sorted(report.items(), key=lambda x: x[1]["total_ms"], reverse=True))
        return {
            "phases": sorted_report,
            "total_ms": round(sum(r["total_ms"] for r in report.values()), 3),
        }

    def reset(self) -> None:
        self._timings.clear()
        self._counts.clear()


def _excursion(position_data: dict, exit_idx: int, lows: np.ndarray, highs: np.ndarray, n: int) -> tuple[float, float]:
    entry_price = float(position_data.get("entry_price", 0))
    entry_idx = int(position_data.get("entry_idx", exit_idx))
    if entry_price <= 0:
        return 0.0, 0.0
    if n <= 0 or entry_idx < 0 or exit_idx < 0 or entry_idx >= n or exit_idx >= n:
        return 0.0, 0.0
    start = max(0, min(entry_idx, exit_idx))
    end = max(start, min(exit_idx, n - 1)) + 1
    low_window = lows[start:end] if len(lows) >= end else np.empty(0)
    high_window = highs[start:end] if len(highs) >= end else np.empty(0)
    finite_lows = low_window[np.isfinite(low_window)]
    finite_highs = high_window[np.isfinite(high_window)]
    if len(finite_lows) == 0 or len(finite_highs) == 0:
        return 0.0, 0.0
    mae = (float(np.min(finite_lows)) / entry_price - 1) * 100
    mfe = (float(np.max(finite_highs)) / entry_price - 1) * 100
    return round(mae, 2), round(mfe, 2)


def _simulate_call_auction_fill(open_price: float, rng: np.random.Generator = None) -> float:
    if rng is None:
        rng = np.random.default_rng()
    noise = rng.uniform(-0.001, 0.001)
    return open_price * (1 + noise)


def _simulate_twap_fill(price: float, shares: int, daily_amount: float,
                         n_slices: int = 4, rng: np.random.Generator = None) -> float:
    if daily_amount <= 0 or shares * price < daily_amount * 0.01:
        return price
    if rng is None:
        rng = np.random.default_rng()
    total_fill = 0.0
    remaining = shares
    per_slice = max(shares // n_slices, 1)
    for s in range(n_slices):
        slice_shares = min(per_slice, remaining) if s < n_slices - 1 else remaining
        remaining -= slice_shares
        noise = rng.normal(0, 0.001)
        total_fill += slice_shares * price * (1 + noise)
    return total_fill / shares


def _check_limit_price(prev_close: float, price: float, is_buy: bool,
                       limit_pct: float = 0.10) -> tuple[bool, float]:
    if prev_close <= 0:
        return True, 1.0
    upper = prev_close * (1 + limit_pct)
    lower = prev_close * (1 - limit_pct)
    if is_buy and price >= upper:
        fill_prob = max(0.1, 1.0 - (price - upper) / (upper * 0.01 + 1e-9))
        return False, min(fill_prob, 0.9)
    if not is_buy and price <= lower:
        fill_prob = max(0.1, 1.0 - (lower - price) / (lower * 0.01 + 1e-9))
        return False, min(fill_prob, 0.9)
    return True, 1.0


def _get_limit_pct(symbol: str) -> float:
    if symbol.startswith(("3", "68")):
        return 0.20
    if symbol.startswith("8"):
        return 0.30
    return 0.10


def _get_strategy_min_bars(strategy_name: str, params: dict | None = None) -> int:
    _min_bars = {
        "ma_cross": 30, "dual_ma": 30, "macd": 45, "rsi": 30,
        "supertrend": 25, "kdj": 25, "bollinger": 35, "bollinger_breakout": 35,
        "momentum": 35, "volume_breakout": 35, "multi_factor": 65,
        "adaptive_trend": 70, "mean_reversion_pro": 55, "mean_reversion": 55,
        "vol_squeeze": 45, "volatility_squeeze": 45,
        "ichimoku": 90, "ichimoku_cloud": 90,
        "vwap_deviation": 40, "vwap": 40,
        "order_flow": 30, "order_flow_imbalance": 30,
        "regime_switching": 90, "regime": 90,
        "fractal_breakout": 35, "fractal": 35,
        "wyckoff": 70, "wyckoff_accumulation": 70,
        "elliott_wave": 140, "elliott": 140,
        "market_microstructure": 35, "microstructure": 35,
        "copula": 80, "copula_correlation": 80,
        "quantile": 80, "quantile_regression": 80,
        "rsi_mean_reversion": 30,
        "turtle": 35, "turtle_trading": 35,
        "dual_thrust": 30,
        "atr_channel": 30, "atr_channel_breakout": 30,
        "donchian": 30, "donchian_channel": 30,
        "chande_kroll": 40, "chande_kroll_stop": 40,
        "vw_macd": 50, "volume_weighted_macd": 50,
        "ornstein_uhlenbeck": 60,
        "kaufman_adaptive": 40,
        "garch_volatility": 60,
        "mtf_momentum": 50, "multi_timeframe_momentum": 50,
        "adx_trend": 55, "adx_trend_strength": 55,
        "cmf": 50, "chaikin_money_flow": 50,
        "psar": 25, "parabolic_sar": 25,
        "hurst": 100, "hurst_exponent": 100,
        "pairs": 65, "pairs_trading": 65,
    }
    return _min_bars.get(strategy_name, 30)
