from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.regression.linear_model import OLS
from statsmodels.tsa.stattools import adfuller
from statsmodels.tsa.vector_ar.vecm import coint_johansen

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CointegrationTestResult:
    symbol_y: str
    symbol_x: str
    p_value: float
    hedge_ratio: float
    half_life: float
    hurst_exponent: float
    test_method: str
    is_cointegrated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol_y": self.symbol_y,
            "symbol_x": self.symbol_x,
            "p_value": self.p_value,
            "hedge_ratio": self.hedge_ratio,
            "half_life": self.half_life,
            "hurst_exponent": self.hurst_exponent,
            "test_method": self.test_method,
            "is_cointegrated": self.is_cointegrated,
        }


@dataclass(frozen=True)
class SpreadState:
    z_score: float
    mean: float
    std: float
    half_life: float
    is_entry_signal: bool
    is_exit_signal: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "z_score": self.z_score,
            "mean": self.mean,
            "std": self.std,
            "half_life": self.half_life,
            "is_entry_signal": self.is_entry_signal,
            "is_exit_signal": self.is_exit_signal,
        }


def _compute_half_life(spread: np.ndarray) -> float:
    if len(spread) < 2:
        return float("inf")
    lag = spread[:-1]
    diff = spread[1:] - lag
    x = np.column_stack([lag, np.ones(len(lag))])
    try:
        coeffs = np.linalg.lstsq(x, diff, rcond=None)[0]
    except np.linalg.LinAlgError:
        return float("inf")
    phi = 1.0 + float(coeffs[0])
    if phi <= 0.0:
        return 0.0
    if phi >= 1.0:
        return float("inf")
    hl = -math.log(2) / math.log(phi)
    return max(0.0, hl)


def engle_granger_test(
    y: pd.Series,
    x: pd.Series,
    significance: float = 0.05,
) -> CointegrationTestResult:
    symbol_y = str(y.name) if y.name is not None else "Y"
    symbol_x = str(x.name) if x.name is not None else "X"

    common_idx = y.index.intersection(x.index)
    if len(common_idx) < 30:
        return CointegrationTestResult(
            symbol_y=symbol_y,
            symbol_x=symbol_x,
            p_value=1.0,
            hedge_ratio=0.0,
            half_life=float("inf"),
            hurst_exponent=0.5,
            test_method="engle_granger",
            is_cointegrated=False,
        )

    y_vals = y.loc[common_idx].values.astype(float)
    x_vals = x.loc[common_idx].values.astype(float)

    x_with_const = np.column_stack([x_vals, np.ones(len(x_vals))])
    ols_model = OLS(y_vals, x_with_const)
    ols_result = ols_model.fit()
    hedge_ratio = float(ols_result.params[0])

    residuals = y_vals - hedge_ratio * x_vals
    try:
        adf_result = adfuller(residuals, autolag="AIC")
        p_value = float(adf_result[1])
    except Exception as e:
        logger.debug("ADF test failed for (%s, %s): %s", symbol_y, symbol_x, e)
        p_value = 1.0

    half_life = _compute_half_life(residuals)
    hurst = compute_hurst(pd.Series(residuals))
    is_cointegrated = p_value < significance

    return CointegrationTestResult(
        symbol_y=symbol_y,
        symbol_x=symbol_x,
        p_value=p_value,
        hedge_ratio=hedge_ratio,
        half_life=half_life,
        hurst_exponent=hurst,
        test_method="engle_granger",
        is_cointegrated=is_cointegrated,
    )


def johansen_test(
    prices: pd.DataFrame,
    significance: float = 0.05,
) -> list[CointegrationTestResult]:
    if len(prices.columns) < 2:
        logger.warning("Johansen test requires at least 2 variables")
        return []

    prices_clean = prices.dropna()
    if len(prices_clean) < 30:
        logger.warning("Insufficient data for Johansen test: %d rows", len(prices_clean))
        return []

    try:
        result = coint_johansen(prices_clean.values.astype(float), det_order=0, k_ar_diff=1)
    except Exception as e:
        logger.error("Johansen test computation failed: %s", e)
        return []

    symbols = list(prices.columns)
    n = len(symbols)
    sig_idx_map = {0.10: 0, 0.05: 1, 0.01: 2}
    sig_idx = sig_idx_map.get(significance, 1)

    results: list[CointegrationTestResult] = []

    for i in range(n - 1):
        trace_stat = float(result.lr1[i])
        crit_val = float(result.cvt[i, sig_idx])

        if trace_stat <= crit_val:
            continue

        evec = result.evec[:, i].copy()
        if abs(evec[0]) < 1e-12:
            continue
        evec_normalized = evec / evec[0]

        if trace_stat > float(result.cvt[i, 2]):
            approx_p = 0.01
        elif trace_stat > float(result.cvt[i, 1]):
            approx_p = 0.05
        elif trace_stat > float(result.cvt[i, 0]):
            approx_p = 0.10
        else:
            approx_p = 1.0

        for j in range(1, n):
            symbol_y = symbols[0]
            symbol_x = symbols[j]
            beta = -float(evec_normalized[j])

            spread = prices_clean[symbol_y].values - beta * prices_clean[symbol_x].values
            half_life = _compute_half_life(spread)
            hurst = compute_hurst(pd.Series(spread))

            results.append(CointegrationTestResult(
                symbol_y=symbol_y,
                symbol_x=symbol_x,
                p_value=approx_p,
                hedge_ratio=beta,
                half_life=half_life,
                hurst_exponent=hurst,
                test_method="johansen",
                is_cointegrated=approx_p < significance,
            ))

    return results


def compute_hurst(series: pd.Series, max_lag: int = 100) -> float:
    vals = series.dropna().values.astype(float)
    if len(vals) < 20:
        return 0.5

    effective_max_lag = min(max_lag, len(vals) - 1)
    if effective_max_lag < 2:
        return 0.5

    lags: list[int] = []
    tau: list[float] = []
    for lag in range(2, effective_max_lag + 1):
        diff = vals[lag:] - vals[:-lag]
        s = float(np.std(diff, ddof=1))
        if s > 1e-10:
            lags.append(lag)
            tau.append(s)

    if len(lags) < 2:
        return 0.5

    log_lags = np.log(lags)
    log_tau = np.log(tau)
    try:
        poly = np.polyfit(log_lags, log_tau, 1)
    except (np.linalg.LinAlgError, ValueError):
        return 0.5

    hurst = float(poly[0])
    return max(0.0, min(1.0, hurst))


class KalmanHedgeRatio:
    def __init__(
        self,
        observation_noise: float = 1e-2,
        process_noise: float = 1e-5,
        initial_beta: float = 0.0,
        initial_covariance: float = 1.0,
    ) -> None:
        self._beta = initial_beta
        self._P = initial_covariance
        self._Q = process_noise
        self._R = observation_noise

    def update(self, y: float, x: float) -> float:
        self._P += self._Q

        innovation = y - self._beta * x
        state_var = x * x * self._P + self._R
        if abs(state_var) < 1e-15:
            return self._beta

        kalman_gain = self._P * x / state_var
        self._beta += kalman_gain * innovation
        self._P = max((1.0 - kalman_gain * x) * self._P, 1e-12)

        return self._beta

    def get_spread(self, y: float, x: float) -> float:
        return y - self._beta * x

    @property
    def beta(self) -> float:
        return self._beta

    @property
    def covariance(self) -> float:
        return self._P


class PairMiningEngine:
    def __init__(
        self,
        pvalue_threshold: float = 0.05,
        method: str = "engle_granger",
    ) -> None:
        self._pvalue_threshold = pvalue_threshold
        self._method = method

    def find_cointegrated_pairs(
        self,
        prices_df: pd.DataFrame,
        universe: list[str],
        pvalue_threshold: float | None = None,
        method: str | None = None,
    ) -> list[CointegrationTestResult]:
        threshold = pvalue_threshold if pvalue_threshold is not None else self._pvalue_threshold
        test_method = method if method is not None else self._method

        available = [s for s in universe if s in prices_df.columns]
        if len(available) < 2:
            logger.warning("Not enough symbols in price data for pair mining")
            return []

        pairs = list(combinations(available, 2))
        logger.info("Testing %d pair combinations with %s method", len(pairs), test_method)

        results: list[CointegrationTestResult] = []
        for sym_y, sym_x in pairs:
            try:
                y = prices_df[sym_y].dropna()
                x = prices_df[sym_x].dropna()

                if test_method == "engle_granger":
                    result = engle_granger_test(y, x, significance=threshold)
                elif test_method == "johansen":
                    pair_df = prices_df[[sym_y, sym_x]].dropna()
                    johansen_results = johansen_test(pair_df, significance=threshold)
                    if not johansen_results:
                        continue
                    result = johansen_results[0]
                else:
                    logger.error("Unknown cointegration test method: %s", test_method)
                    continue

                if not result.is_cointegrated:
                    continue
                if result.half_life is None or not (1.0 < result.half_life < 60.0):
                    continue
                if result.hurst_exponent >= 0.5:
                    continue

                results.append(result)
            except Exception as e:
                logger.debug("Pair (%s, %s) test failed: %s", sym_y, sym_x, e)

        results.sort(key=lambda r: r.p_value)
        logger.info("Found %d cointegrated pairs meeting all criteria", len(results))
        return results

    def find_pairs_by_industry(
        self,
        prices_df: pd.DataFrame,
        industry_map: dict[str, str],
        pvalue_threshold: float | None = None,
        method: str | None = None,
    ) -> list[CointegrationTestResult]:
        industry_groups: dict[str, list[str]] = {}
        for symbol, industry in industry_map.items():
            if symbol in prices_df.columns:
                industry_groups.setdefault(industry, []).append(symbol)

        all_results: list[CointegrationTestResult] = []
        for industry, symbols in industry_groups.items():
            if len(symbols) < 2:
                continue
            logger.info("Mining pairs in industry '%s' with %d symbols", industry, len(symbols))
            results = self.find_cointegrated_pairs(
                prices_df, symbols, pvalue_threshold, method,
            )
            all_results.extend(results)

        all_results.sort(key=lambda r: r.p_value)
        return all_results


class SpreadMonitor:
    def __init__(
        self,
        window: int = 60,
        entry_threshold: float = 2.0,
        exit_threshold: float = 0.5,
    ) -> None:
        self._window = window
        self._entry_threshold = entry_threshold
        self._exit_threshold = exit_threshold
        self._history: list[float] = []

    def update(self, spread: float) -> SpreadState:
        self._history.append(spread)
        if len(self._history) > self._window * 2:
            self._history = self._history[-(self._window * 2):]

        window_data = (
            self._history[-self._window:]
            if len(self._history) >= self._window
            else self._history
        )

        arr = np.array(window_data)
        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=1)) if len(arr) >= 2 else 0.0

        z_score = 0.0 if std < 1e-10 else (spread - mean) / std

        half_life = 0.0
        if len(self._history) >= 20:
            half_life = _compute_half_life(np.array(self._history))

        is_entry = abs(z_score) > self._entry_threshold
        is_exit = abs(z_score) < self._exit_threshold

        return SpreadState(
            z_score=z_score,
            mean=mean,
            std=std,
            half_life=half_life,
            is_entry_signal=is_entry,
            is_exit_signal=is_exit,
        )

    @property
    def history(self) -> list[float]:
        return list(self._history)

    def reset(self) -> None:
        self._history.clear()


def estimate_pair_capacity(
    pair: CointegrationTestResult,
    adv_y: float,
    adv_x: float,
    max_participation: float = 0.05,
) -> float:
    if adv_y <= 0 or adv_x <= 0:
        return 0.0
    capacity_y = adv_y * max_participation
    capacity_x = adv_x * max_participation
    return min(capacity_y, capacity_x)
