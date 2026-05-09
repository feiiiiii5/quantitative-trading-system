import logging
from typing import Literal

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

_MIN_DATA_POINTS = 30


class FactorMiner:

    def __init__(self, forward_period: int = 5) -> None:
        self._forward_period = forward_period

    def generate_technical_factors(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or len(df) < _MIN_DATA_POINTS:
            logger.warning("Insufficient data for technical factor generation: %d rows", len(df) if df is not None else 0)
            return pd.DataFrame()

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        open_ = df["open"].astype(float) if "open" in df.columns else close
        volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series(np.ones(len(df)), index=df.index)

        factors = pd.DataFrame(index=df.index)

        self._add_momentum_factors(factors, close, high, low)
        self._add_ma_factors(factors, close)
        self._add_volatility_factors(factors, close, high, low)
        self._add_volume_factors(factors, close, high, low, volume)
        self._add_oscillator_factors(factors, close, high, low)
        self._add_trend_factors(factors, close, high, low)
        self._add_price_factors(factors, close, high, low, open_)

        factors = factors.replace([np.inf, -np.inf], np.nan)
        logger.info("Generated %d technical factors", len(factors.columns))
        return factors

    def generate_statistical_factors(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or len(df) < _MIN_DATA_POINTS:
            logger.warning("Insufficient data for statistical factor generation")
            return pd.DataFrame()

        close = df["close"].astype(float)
        returns = close.pct_change()

        factors = pd.DataFrame(index=df.index)

        for window in [20, 60, 120]:
            if len(close) < window:
                continue
            factors[f"skewness_{window}"] = returns.rolling(window).skew()
            factors[f"kurtosis_{window}"] = returns.rolling(window).kurt()
            factors[f"autocorr_{window}"] = returns.rolling(window).apply(
                lambda x: x.autocorr(lag=1) if len(x) > 2 else np.nan, raw=False
            )
            factors[f"hurst_{window}"] = returns.rolling(window).apply(
                _compute_hurst, raw=True
            )
            factors[f"realized_vol_{window}"] = returns.rolling(window).std() * np.sqrt(252)
            factors[f"downside_vol_{window}"] = returns.rolling(window).apply(
                lambda x: np.sqrt(np.mean(np.minimum(x, 0) ** 2)) if len(x) > 1 else np.nan, raw=True
            ) * np.sqrt(252)
            factors[f"upside_vol_{window}"] = returns.rolling(window).apply(
                lambda x: np.sqrt(np.mean(np.maximum(x, 0) ** 2)) if len(x) > 1 else np.nan, raw=True
            ) * np.sqrt(252)

        factors[f"sharpe_20"] = returns.rolling(20).mean() / (returns.rolling(20).std() + 1e-10) * np.sqrt(252)
        factors[f"sortino_20"] = returns.rolling(20).mean() / (factors[f"downside_vol_20"] + 1e-10)
        factors[f"calmar_60"] = returns.rolling(60).mean() * 252 / (
            close.rolling(60).apply(_max_drawdown, raw=True) + 1e-10
        )

        factors = factors.replace([np.inf, -np.inf], np.nan)
        logger.info("Generated %d statistical factors", len(factors.columns))
        return factors

    def rank_factors(
        self,
        factor_df: pd.DataFrame,
        returns: pd.Series,
        method: Literal["ic", "mi"] = "ic",
    ) -> pd.DataFrame:
        if factor_df.empty or returns.empty:
            return pd.DataFrame()

        forward_returns = returns.shift(-self._forward_period)
        aligned = factor_df.dropna(how="all").index.intersection(forward_returns.dropna().index)

        if len(aligned) < _MIN_DATA_POINTS:
            logger.warning("Insufficient overlapping data for factor ranking: %d", len(aligned))
            return pd.DataFrame()

        results: list[dict[str, float]] = []
        for col in factor_df.columns:
            factor_vals = factor_df.loc[aligned, col].dropna()
            ret_vals = forward_returns.loc[factor_vals.index].dropna()
            common = factor_vals.index.intersection(ret_vals.index)

            if len(common) < _MIN_DATA_POINTS:
                continue

            f = factor_vals.loc[common]
            r = ret_vals.loc[common]

            if method == "ic":
                score = self.compute_ic(f, r)
            elif method == "mi":
                score = _compute_mutual_info(f, r)
            else:
                raise ValueError(f"Unknown ranking method: {method}")

            turnover = self.compute_turnover(factor_df[col])
            results.append({
                "factor": col,
                "score": score,
                "abs_score": abs(score),
                "turnover": turnover,
            })

        ranked = pd.DataFrame(results).sort_values("abs_score", ascending=False).reset_index(drop=True)
        logger.info("Ranked %d factors using method=%s", len(ranked), method)
        return ranked

    def select_top_factors(self, ranked: pd.DataFrame, n: int = 20) -> list[str]:
        if ranked.empty:
            return []
        return ranked.head(n)["factor"].tolist()

    @staticmethod
    def compute_ic(factor: pd.Series, forward_returns: pd.Series) -> float:
        common = factor.dropna().index.intersection(forward_returns.dropna().index)
        if len(common) < _MIN_DATA_POINTS:
            return 0.0
        corr, _ = stats.spearmanr(factor.loc[common], forward_returns.loc[common])
        return float(corr) if np.isfinite(corr) else 0.0

    @staticmethod
    def compute_turnover(factor: pd.Series, window: int = 5) -> float:
        ranked = factor.rank(pct=True)
        shifted = ranked.shift(window)
        common = ranked.dropna().index.intersection(shifted.dropna().index)
        if len(common) < window:
            return 1.0
        diff = (ranked.loc[common] - shifted.loc[common]).abs()
        return float(diff.mean())

    @staticmethod
    def neutralize(factor: pd.Series, industry: pd.Series) -> pd.Series:
        common = factor.dropna().index.intersection(industry.dropna().index)
        if len(common) == 0:
            return factor

        result = factor.copy()
        for ind in industry.loc[common].unique():
            mask = industry.loc[common] == ind
            idx = industry.loc[common][mask].index
            group_vals = factor.loc[idx]
            if len(group_vals) > 1:
                result.loc[idx] = group_vals - group_vals.mean()
        return result

    def _add_momentum_factors(self, factors: pd.DataFrame, close: pd.Series, high: pd.Series, low: pd.Series) -> None:
        for period in [5, 10, 20, 60, 120]:
            factors[f"roc_{period}"] = close.pct_change(period)
            factors[f"momentum_{period}"] = close - close.shift(period)

        factors["rsi_14"] = _compute_rsi(close, 14)
        factors["rsi_6"] = _compute_rsi(close, 6)
        factors["rsi_24"] = _compute_rsi(close, 24)

        delta = close.diff()
        up = delta.clip(lower=0)
        down = (-delta).clip(lower=0)
        for period in [14, 30]:
            ema_up = up.ewm(span=period, adjust=False).mean()
            ema_down = down.ewm(span=period, adjust=False).mean()
            factors[f"cci_{period}"] = (ema_up - ema_down) / (ema_up + ema_down + 1e-10)

        factors["williams_r_14"] = _compute_williams_r(high, low, close, 14)

    def _add_ma_factors(self, factors: pd.DataFrame, close: pd.Series) -> None:
        for period in [5, 10, 20, 60, 120, 250]:
            factors[f"sma_{period}"] = close.rolling(period).mean()
            factors[f"price_to_sma_{period}"] = close / factors[f"sma_{period}"] - 1

        for period in [12, 26, 50]:
            factors[f"ema_{period}"] = close.ewm(span=period, adjust=False).mean()
            factors[f"price_to_ema_{period}"] = close / factors[f"ema_{period}"] - 1

        factors["ema_cross_12_26"] = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        factors["ema_cross_5_20"] = close.ewm(span=5, adjust=False).mean() - close.ewm(span=20, adjust=False).mean()

        factors["dema_20"] = (
            2 * close.ewm(span=20, adjust=False).mean()
            - close.ewm(span=20, adjust=False).mean().ewm(span=20, adjust=False).mean()
        )

    def _add_volatility_factors(self, factors: pd.DataFrame, close: pd.Series, high: pd.Series, low: pd.Series) -> None:
        for period in [10, 20, 60]:
            factors[f"hist_vol_{period}"] = close.pct_change().rolling(period).std() * np.sqrt(252)

        for period in [14, 20]:
            factors[f"atr_{period}"] = _compute_atr(high, low, close, period)
            factors[f"atr_pct_{period}"] = factors[f"atr_{period}"] / close

        for period in [20, 60]:
            sma = close.rolling(period).mean()
            std = close.rolling(period).std()
            factors[f"bb_upper_{period}"] = sma + 2 * std
            factors[f"bb_lower_{period}"] = sma - 2 * std
            factors[f"bb_pct_{period}"] = (close - factors[f"bb_lower_{period}"]) / (4 * std + 1e-10)
            factors[f"bb_width_{period}"] = 4 * std / (sma + 1e-10)

        factors["parkinson_vol"] = np.sqrt(
            (np.log(high / low) ** 2).rolling(20).mean() / (4 * np.log(2))
        ) * np.sqrt(252)

    def _add_volume_factors(self, factors: pd.DataFrame, close: pd.Series, high: pd.Series, low: pd.Series, volume: pd.Series) -> None:
        factors["obv"] = _compute_obv(close, volume)
        factors["obv_sma_20"] = factors["obv"].rolling(20).mean()

        for period in [10, 20, 60]:
            factors[f"volume_sma_{period}"] = volume.rolling(period).mean()
            factors[f"volume_ratio_{period}"] = volume / factors[f"volume_sma_{period}"]

        typical_price = (high + low + close) / 3
        for period in [20]:
            mf = typical_price * volume
            mf_pos = mf.where(typical_price > typical_price.shift(1), 0)
            mf_neg = mf.where(typical_price < typical_price.shift(1), 0)
            factors[f"cmf_{period}"] = (
                mf_pos.rolling(period).sum() / (mf.rolling(period).sum() + 1e-10)
                - mf_neg.rolling(period).sum() / (mf.rolling(period).sum() + 1e-10)
            )

        factors["vwap"] = _compute_vwap(high, low, close, volume)
        factors["price_to_vwap"] = close / factors["vwap"] - 1

        factors["vpt"] = _compute_vpt(close, volume)
        factors["vpt_sma_20"] = factors["vpt"].rolling(20).mean()

    def _add_oscillator_factors(self, factors: pd.DataFrame, close: pd.Series, high: pd.Series, low: pd.Series) -> None:
        macd_line, signal_line, hist = _compute_macd(close)
        factors["macd"] = macd_line
        factors["macd_signal"] = signal_line
        factors["macd_hist"] = hist
        factors["macd_hist_ratio"] = hist / (close + 1e-10)

        for period in [14, 20]:
            factors[f"stoch_k_{period}"] = _compute_stoch_k(high, low, close, period)
            factors[f"stoch_d_{period}"] = factors[f"stoch_k_{period}"].rolling(3).mean()

        factors["cci_20"] = _compute_cci(high, low, close, 20)

        factors["ultimate_osc"] = _compute_ultimate_oscillator(high, low, close)

    def _add_trend_factors(self, factors: pd.DataFrame, close: pd.Series, high: pd.Series, low: pd.Series) -> None:
        for period in [14, 20]:
            factors[f"adx_{period}"] = _compute_adx(high, low, close, period)

        factors["plus_di_14"] = _compute_plus_di(high, low, close, 14)
        factors["minus_di_14"] = _compute_minus_di(high, low, close, 14)
        factors["di_diff_14"] = factors["plus_di_14"] - factors["minus_di_14"]

        factors["aroon_up_25"], factors["aroon_down_25"] = _compute_aroon(high, low, 25)
        factors["aroon_osc_25"] = factors["aroon_up_25"] - factors["aroon_down_25"]

    def _add_price_factors(self, factors: pd.DataFrame, close: pd.Series, high: pd.Series, low: pd.Series, open_: pd.Series) -> None:
        factors["gap"] = open_ / close.shift(1) - 1
        factors["intraday_return"] = close / open_ - 1
        factors["upper_shadow"] = (high - pd.concat([close, open_], axis=1).max(axis=1)) / (high - low + 1e-10)
        factors["lower_shadow"] = (pd.concat([close, open_], axis=1).min(axis=1) - low) / (high - low + 1e-10)
        factors["body_ratio"] = (close - open_).abs() / (high - low + 1e-10)

        factors["high_low_range"] = (high - low) / close
        factors["close_open_range"] = (close - open_).abs() / close

        for period in [20, 60]:
            factors[f"high_max_{period}"] = high.rolling(period).max()
            factors[f"low_min_{period}"] = low.rolling(period).min()
            factors[f"price_position_{period}"] = (
                (close - factors[f"low_min_{period}"])
                / (factors[f"high_max_{period}"] - factors[f"low_min_{period}"] + 1e-10)
            )


def _compute_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(span=period, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(span=period, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100 - 100 / (1 + rs)


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _compute_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff())
    direction.iloc[0] = 0
    return (volume * direction).cumsum()


def _compute_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    typical_price = (high + low + close) / 3
    cum_tp_vol = (typical_price * volume).cumsum()
    cum_vol = volume.cumsum()
    return cum_tp_vol / (cum_vol + 1e-10)


def _compute_vpt(close: pd.Series, volume: pd.Series) -> pd.Series:
    pct = close.pct_change()
    pct.iloc[0] = 0
    return (volume * pct).cumsum()


def _compute_macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _compute_stoch_k(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    lowest = low.rolling(period).min()
    highest = high.rolling(period).max()
    return 100 * (close - lowest) / (highest - lowest + 1e-10)


def _compute_cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    tp = (high + low + close) / 3
    sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - sma) / (0.015 * mad + 1e-10)


def _compute_ultimate_oscillator(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    bp = close - pd.concat([low, close.shift(1)], axis=1).min(axis=1)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    avg7 = bp.rolling(7).sum() / (tr.rolling(7).sum() + 1e-10)
    avg14 = bp.rolling(14).sum() / (tr.rolling(14).sum() + 1e-10)
    avg28 = bp.rolling(28).sum() / (tr.rolling(28).sum() + 1e-10)

    return 100 * (4 * avg7 + 2 * avg14 + avg28) / 7


def _compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    plus_dm = (high - high.shift(1)).clip(lower=0)
    minus_dm = (low.shift(1) - low).clip(lower=0)

    mask = (high - high.shift(1)) < (low.shift(1) - low)
    plus_dm[mask] = 0
    minus_dm[~mask] = 0

    atr = _compute_atr(high, low, close, period)
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / (atr + 1e-10)
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / (atr + 1e-10)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    return dx.ewm(span=period, adjust=False).mean()


def _compute_plus_di(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    plus_dm = (high - high.shift(1)).clip(lower=0)
    mask = (high - high.shift(1)) < (low.shift(1) - low)
    plus_dm[mask] = 0
    atr = _compute_atr(high, low, close, period)
    return 100 * plus_dm.ewm(span=period, adjust=False).mean() / (atr + 1e-10)


def _compute_minus_di(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    minus_dm = (low.shift(1) - low).clip(lower=0)
    mask = (high - high.shift(1)) > (low.shift(1) - low)
    minus_dm[mask] = 0
    atr = _compute_atr(high, low, close, period)
    return 100 * minus_dm.ewm(span=period, adjust=False).mean() / (atr + 1e-10)


def _compute_aroon(high: pd.Series, low: pd.Series, period: int) -> tuple[pd.Series, pd.Series]:
    days_since_high = high.rolling(period + 1).apply(lambda x: period - np.argmax(x), raw=True)
    days_since_low = low.rolling(period + 1).apply(lambda x: period - np.argmin(x), raw=True)
    aroon_up = 100 * (period - days_since_high) / period
    aroon_down = 100 * (period - days_since_low) / period
    return aroon_up, aroon_down


def _compute_williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    highest = high.rolling(period).max()
    lowest = low.rolling(period).min()
    return -100 * (highest - close) / (highest - lowest + 1e-10)


def _compute_hurst(returns_array: np.ndarray) -> float:
    if len(returns_array) < 20:
        return np.nan
    ts = np.cumsum(returns_array - np.mean(returns_array))
    max_lag = min(len(ts) // 2, 50)
    if max_lag < 2:
        return np.nan
    lags = range(2, max_lag + 1)
    tau_values = []
    for lag in lags:
        diff = ts[lag:] - ts[:-lag]
        if len(diff) > 0:
            tau_values.append(np.std(diff))
        else:
            tau_values.append(0)
    tau_arr = np.array(tau_values)
    valid = tau_arr > 0
    if valid.sum() < 2:
        return np.nan
    log_lags = np.log(np.array(list(lags))[valid])
    log_tau = np.log(tau_arr[valid])
    try:
        slope, _ = np.polyfit(log_lags, log_tau, 1)
        return float(slope)
    except (np.linalg.LinAlgError, ValueError):
        return np.nan


def _max_drawdown(prices: np.ndarray) -> float:
    if len(prices) < 2:
        return 0.0
    running_max = np.maximum.accumulate(prices)
    drawdowns = (running_max - prices) / (running_max + 1e-10)
    return float(np.max(drawdowns))


def _compute_mutual_info(factor: pd.Series, returns: pd.Series) -> float:
    try:
        from sklearn.feature_selection import mutual_info_regression

        f_vals = factor.values.reshape(-1, 1)
        r_vals = returns.values
        valid = np.isfinite(f_vals.flatten()) & np.isfinite(r_vals)
        if valid.sum() < _MIN_DATA_POINTS:
            return 0.0
        mi = mutual_info_regression(
            f_vals[valid], r_vals[valid], n_neighbors=5, random_state=42
        )
        return float(mi[0])
    except ImportError:
        logger.warning("scikit-learn not available, falling back to IC for mutual information")
        corr, _ = stats.spearmanr(factor, returns)
        return float(abs(corr)) if np.isfinite(corr) else 0.0
