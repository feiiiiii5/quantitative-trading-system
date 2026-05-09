__all__ = [
    "sma_numba",
    "ema_numba",
    "rsi_numba",
    "atr_numba",
    "bbands_numba",
    "NUMBA_AVAILABLE",
]

import logging

import numpy as np

logger = logging.getLogger(__name__)

try:
    from numba import njit, prange

    NUMBA_AVAILABLE = True
    logger.debug("Numba JIT available")
except ImportError:
    NUMBA_AVAILABLE = False
    logger.debug("Numba not available, using pure NumPy fallback")

    def njit(*args, **kwargs):
        def decorator(fn):
            return fn
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator

    prange = range


@njit(cache=True)
def _sma_core(data: np.ndarray, period: int) -> np.ndarray:
    n = len(data)
    result = np.full(n, np.nan)
    if n < period:
        return result
    s = 0.0
    for i in range(period):
        s += data[i]
    result[period - 1] = s / period
    for i in range(period, n):
        s += data[i] - data[i - period]
        result[i] = s / period
    return result


@njit(cache=True)
def _ema_core(data: np.ndarray, period: int) -> np.ndarray:
    n = len(data)
    result = np.full(n, np.nan)
    if n < period:
        return result
    multiplier = 2.0 / (period + 1)
    s = 0.0
    for i in range(period):
        s += data[i]
    result[period - 1] = s / period
    for i in range(period, n):
        result[i] = (data[i] - result[i - 1]) * multiplier + result[i - 1]
    return result


@njit(cache=True)
def _rsi_core(data: np.ndarray, period: int) -> np.ndarray:
    n = len(data)
    result = np.full(n, np.nan)
    if n < period + 1:
        return result
    gains = np.zeros(n)
    losses = np.zeros(n)
    for i in range(1, n):
        diff = data[i] - data[i - 1]
        if diff > 0:
            gains[i] = diff
        else:
            losses[i] = -diff
    avg_gain = 0.0
    avg_loss = 0.0
    for i in range(1, period + 1):
        avg_gain += gains[i]
        avg_loss += losses[i]
    avg_gain /= period
    avg_loss /= period
    if avg_loss < 1e-12:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - 100.0 / (1.0 + rs)
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss < 1e-12:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - 100.0 / (1.0 + rs)
    return result


@njit(cache=True)
def _atr_core(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    n = len(high)
    result = np.full(n, np.nan)
    if n < period + 1:
        return result
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, max(hc, lc))
    s = 0.0
    for i in range(period):
        s += tr[i]
    result[period - 1] = s / period
    for i in range(period, n):
        result[i] = (result[i - 1] * (period - 1) + tr[i]) / period
    return result


@njit(cache=True)
def _bbands_core(data: np.ndarray, period: int, std_dev: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(data)
    middle = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    if n < period:
        return upper, middle, lower
    for i in range(period - 1, n):
        s = 0.0
        for j in range(i - period + 1, i + 1):
            s += data[j]
        mean = s / period
        var = 0.0
        for j in range(i - period + 1, i + 1):
            var += (data[j] - mean) ** 2
        std = np.sqrt(var / period)
        middle[i] = mean
        upper[i] = mean + std_dev * std
        lower[i] = mean - std_dev * std
    return upper, middle, lower


def sma_numba(data: np.ndarray, period: int) -> np.ndarray:
    arr = np.asarray(data, dtype=np.float64)
    return _sma_core(arr, period)


def ema_numba(data: np.ndarray, period: int) -> np.ndarray:
    arr = np.asarray(data, dtype=np.float64)
    return _ema_core(arr, period)


def rsi_numba(data: np.ndarray, period: int = 14) -> np.ndarray:
    arr = np.asarray(data, dtype=np.float64)
    return _rsi_core(arr, period)


def atr_numba(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)
    return _atr_core(h, l, c, period)


def bbands_numba(
    data: np.ndarray,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    arr = np.asarray(data, dtype=np.float64)
    return _bbands_core(arr, period, std_dev)
