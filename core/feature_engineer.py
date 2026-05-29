"""
特征工程管道 - Feature Engineering Pipeline
将原始OHLCV数据转换为ML模型就绪的特征矩阵

特征类别:
1. 价格形态特征 - 收益率、波动率、布林带
2. 技术指标特征 - RSI、MACD、KDJ、CCI、ATR
3. 量价特征 - OBV、成交量变化率、资金流
4. 趋势特征 - ADX、趋势强度、价格位置
5. 统计特征 - 偏度、峰度、收益率分布
6. 跨周期特征 - 多时间框架动量
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class FeatureCategory(Enum):
    PRICE = "price"
    TECHNICAL = "technical"
    VOLUME = "volume"
    TREND = "trend"
    STATISTICAL = "statistical"
    CROSS_PERIOD = "cross_period"


@dataclass
class FeatureConfig:
    include_categories: list[FeatureCategory] | None = None
    lookback_periods: list[int] = field(default_factory=lambda: [5, 10, 20, 60])
    normalize: bool = False
    fill_na_method: Literal["ffill", "bfill", "zero", "mean"] = "zero"
    target_column: str = "close"
    prediction_horizon: int = 1


@dataclass
class FeatureResult:
    features: pd.DataFrame
    target: pd.Series | None
    feature_names: list[str]
    n_samples: int
    feature_categories: dict[str, FeatureCategory]


class FeatureEngineer:
    def __init__(self, config: FeatureConfig | None = None):
        self._config = config or FeatureConfig()
        self._feature_names: list[str] = []
        self._feature_categories: dict[str, FeatureCategory] = {}

    def build_features(self, df: pd.DataFrame) -> FeatureResult:
        if df is None or len(df) < 5:
            return FeatureResult(
                features=pd.DataFrame(),
                target=None,
                feature_names=[],
                n_samples=0,
                feature_categories={},
            )

        df = df.copy()
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        self._feature_names.clear()
        self._feature_categories.clear()

        categories = (
            self._config.include_categories
            or [
                FeatureCategory.PRICE,
                FeatureCategory.TECHNICAL,
                FeatureCategory.VOLUME,
                FeatureCategory.TREND,
                FeatureCategory.STATISTICAL,
            ]
        )

        feature_frames: list[pd.DataFrame] = []

        if FeatureCategory.PRICE in categories:
            price_feats = self._build_price_features(df)
            feature_frames.append(price_feats)

        if FeatureCategory.TECHNICAL in categories:
            tech_feats = self._build_technical_features(df)
            feature_frames.append(tech_feats)

        if FeatureCategory.VOLUME in categories:
            vol_feats = self._build_volume_features(df)
            feature_frames.append(vol_feats)

        if FeatureCategory.TREND in categories:
            trend_feats = self._build_trend_features(df)
            feature_frames.append(trend_feats)

        if FeatureCategory.STATISTICAL in categories:
            stat_feats = self._build_statistical_features(df)
            feature_frames.append(stat_feats)

        if FeatureCategory.CROSS_PERIOD in categories:
            cross_feats = self._build_cross_period_features(df)
            feature_frames.append(cross_feats)

        features_df = pd.concat(feature_frames, axis=1) if feature_frames else pd.DataFrame()
        features_df = self._fill_na(features_df)
        features_df = features_df.loc[df.index]

        self._feature_names = [c for c in features_df.columns if c in self._feature_names]
        if not self._feature_names:
            self._feature_names = list(features_df.columns)

        target = None
        if self._config.target_column in df.columns:
            target = self._build_target(df)

        return FeatureResult(
            features=features_df,
            target=target,
            feature_names=self._feature_names,
            n_samples=len(features_df),
            feature_categories=dict(self._feature_categories),
        )

    def _add_feature(self, name: str, values: pd.Series, category: FeatureCategory) -> None:
        if name not in self._feature_names:
            self._feature_names.append(name)
        self._feature_categories[name] = category

    def _build_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"]
        high = df["high"]
        low = df["low"]
        result = pd.DataFrame(index=df.index)

        result["returns_1d"] = close.pct_change(1)
        result["returns_5d"] = close.pct_change(5)
        result["returns_10d"] = close.pct_change(10)
        result["returns_20d"] = close.pct_change(20)

        for period in [5, 10, 20, 60]:
            result[f"volatility_{period}d"] = close.pct_change().rolling(period).std()

        for period in [20,]:
            ma = close.rolling(period).mean()
            std = close.rolling(period).std()
            result[f"bb_position_{period}d"] = (close - ma) / (2 * std + 1e-10)
            result[f"bb_upper_{period}d"] = (ma + 2 * std) / close
            result[f"bb_lower_{period}d"] = (ma - 2 * std) / close

        result["high_low_ratio"] = high / (low + 1e-10)
        result["close_open_ratio"] = close / (df["open"] + 1e-10)

        for name, series in result.items():
            self._add_feature(name, series, FeatureCategory.PRICE)

        return result

    def _build_technical_features(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"]
        high = df["high"]
        low = df["low"]
        result = pd.DataFrame(index=df.index)

        result["rsi_14"] = self._rsi(close, 14)
        result["rsi_7"] = self._rsi(close, 7)
        result["rsi_28"] = self._rsi(close, 28)

        macd, signal, hist = self._macd(close)
        result["macd"] = macd
        result["macd_signal"] = signal
        result["macd_histogram"] = hist

        k, d = self._kdjk(close, 9)
        result["kdj_k"] = k
        result["kdj_d"] = d
        result["kdj_j"] = 3 * k - 2 * d

        result["cci_20"] = self._cci(df, 20)
        result["cci_14"] = self._cci(df, 14)

        result["atr_14"] = self._atr(df, 14)
        result["atr_ratio"] = result["atr_14"] / (close + 1e-10)

        slow_k, slow_d = self._stochastic(close, high, low, 14)
        result["stoch_k"] = slow_k
        result["stoch_d"] = slow_d

        for name, series in result.items():
            self._add_feature(name, series, FeatureCategory.TECHNICAL)

        return result

    def _build_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"]
        volume = df["volume"]
        result = pd.DataFrame(index=df.index)

        result["volume_ratio_5d"] = volume / (volume.rolling(5).mean() + 1e-10)
        result["volume_ratio_20d"] = volume / (volume.rolling(20).mean() + 1e-10)
        result["volume_change"] = volume.pct_change()

        obv = (np.sign(close.diff()) * volume).cumsum()
        result["obv"] = obv
        result["obv_ma_ratio"] = obv / (obv.rolling(20).mean() + 1e-10)

        price_vol_corr = close.rolling(20).corr(volume)
        result["price_volume_corr"] = price_vol_corr

        for period in [5, 10, 20]:
            result[f"volume_std_{period}d"] = volume.rolling(period).std()

        for name, series in result.items():
            self._add_feature(name, series, FeatureCategory.VOLUME)

        return result

    def _build_trend_features(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"]
        result = pd.DataFrame(index=df.index)

        for period in [10, 20, 60]:
            ma = close.rolling(period).mean()
            result[f"ma_ratio_{period}d"] = close / (ma + 1e-10)

        adx = self._adx(df)
        result["adx"] = adx

        for period in [10, 20]:
            higher_highs = (df["high"].rolling(period).max() == df["high"]).astype(int)
            lower_lows = (df["low"].rolling(period).min() == df["low"]).astype(int)
            result[f"swing_highs_{period}d"] = higher_highs
            result[f"swing_lows_{period}d"] = lower_lows

        for name, series in result.items():
            self._add_feature(name, series, FeatureCategory.TREND)

        return result

    def _build_statistical_features(self, df: pd.DataFrame) -> pd.DataFrame:
        returns = df["close"].pct_change().dropna()
        result = pd.DataFrame(index=df.index)

        for period in [10, 20, 60]:
            result[f"skewness_{period}d"] = returns.rolling(period, min_periods=period // 2).skew()
            result[f"kurtosis_{period}d"] = returns.rolling(period, min_periods=period // 2).kurt()

        for period in [5, 10, 20]:
            result[f"returns_mean_{period}d"] = returns.rolling(period).mean()
            result[f"returns_std_{period}d"] = returns.rolling(period).std()
            result[f"returns_min_{period}d"] = returns.rolling(period).min()
            result[f"returns_max_{period}d"] = returns.rolling(period).max()

        for name, series in result.items():
            self._add_feature(name, series, FeatureCategory.STATISTICAL)

        return result

    def _build_cross_period_features(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"]
        result = pd.DataFrame(index=df.index)

        short_ma = close.rolling(5).mean()
        long_ma = close.rolling(20).mean()
        result["ma_crossover"] = (short_ma / (long_ma + 1e-10) - 1)

        short_vol = close.pct_change().rolling(5).std()
        long_vol = close.pct_change().rolling(20).std()
        result["vol_regime"] = short_vol / (long_vol + 1e-10)

        for name, series in result.items():
            self._add_feature(name, series, FeatureCategory.CROSS_PERIOD)

        return result

    def _fill_na(self, df: pd.DataFrame) -> pd.DataFrame:
        method = self._config.fill_na_method
        if method == "ffill":
            return df.ffill().fillna(0)
        elif method == "bfill":
            return df.bfill().fillna(0)
        elif method == "zero":
            return df.fillna(0)
        elif method == "mean":
            return df.fillna(df.mean())
        return df.fillna(0)

    def _build_target(self, df: pd.DataFrame) -> pd.Series:
        horizon = self._config.prediction_horizon
        col = self._config.target_column
        returns = df[col].shift(-horizon) / df[col] - 1
        return returns

    @staticmethod
    def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        return 100 - 100 / (1 + rs)

    @staticmethod
    def _macd(
        series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def _kdjk(series: pd.Series, period: int = 9) -> tuple[pd.Series, pd.Series]:
        low_min = series.rolling(window=period).min()
        high_max = series.rolling(window=period).max()
        k = 50 * (series - low_min) / (high_max - low_min + 1e-10)
        d = k.rolling(window=3).mean()
        return k, d

    @staticmethod
    def _cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
        tp = (df["high"] + df["low"] + df["close"]) / 3
        sma = tp.rolling(period).mean()
        mad = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean())
        return (tp - sma) / (0.015 * mad + 1e-10)

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["high"]
        low = df["low"]
        close = df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / period, min_periods=period).mean()

    @staticmethod
    def _stochastic(
        close: pd.Series, high: pd.Series, low: pd.Series, period: int = 14
    ) -> tuple[pd.Series, pd.Series]:
        low_min = low.rolling(window=period).min()
        high_max = high.rolling(window=period).max()
        k = 100 * (close - low_min) / (high_max - low_min + 1e-10)
        slow_k = k.rolling(window=3).mean()
        slow_d = slow_k.rolling(window=3).mean()
        return slow_k, slow_d

    @staticmethod
    def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["high"]
        low = df["low"]
        close = df["close"]
        n = len(close)
        if n <= period:
            return pd.Series(50.0, index=close.index)

        tr = np.maximum(
            high.values[1:] - low.values[1:],
            np.maximum(
                np.abs(high.values[1:] - close.values[:-1]),
                np.abs(low.values[1:] - close.values[:-1]),
            ),
        )
        tr = np.insert(tr, 0, high.iloc[0] - low.iloc[0])
        plus_dm = np.maximum(np.diff(high, prepend=high.iloc[0]), 0)
        minus_dm = np.maximum(-np.diff(low, prepend=low.iloc[0]), 0)
        plus_dm[1:][plus_dm[1:] < minus_dm[:-1]] = 0
        minus_dm[1:][minus_dm[1:] < plus_dm[:-1]] = 0

        atr = pd.Series(tr).ewm(alpha=1 / period, min_periods=period).mean().values
        plus_di = pd.Series(plus_dm).ewm(alpha=1 / period, min_periods=period).mean().values / (atr + 1e-12) * 100
        minus_di = pd.Series(minus_dm).ewm(alpha=1 / period, min_periods=period).mean().values / (atr + 1e-12) * 100
        dx = np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-12) * 100
        adx = pd.Series(dx).ewm(alpha=1 / period, min_periods=period).mean().values
        return pd.Series(adx, index=close.index)

    def get_feature_importance(
        self,
        features: pd.DataFrame,
        target: pd.Series,
        n_features: int = 20,
    ) -> list[tuple[str, float]]:
        if len(features) < 10:
            return []
        valid_mask = target.notna()
        if valid_mask.sum() < 10:
            return []
        feat = features.loc[valid_mask].copy()
        tgt = target.loc[valid_mask].copy()
        try:
            from sklearn.ensemble import RandomForestRegressor
            from sklearn.preprocessing import StandardScaler
            feat = feat.fillna(0).replace([np.inf, -np.inf], 0)
            scaler = StandardScaler()
            feat_scaled = scaler.fit_transform(feat)
            rf = RandomForestRegressor(n_estimators=50, max_depth=5, random_state=42, n_jobs=-1)
            rf.fit(feat_scaled, tgt)
            importances = rf.feature_importances_
            pairs = sorted(zip(feat.columns, importances, strict=True), key=lambda x: x[1], reverse=True)
            return pairs[:n_features]
        except Exception as e:
            logger.debug("Feature importance calculation failed: %s", e)
            return []


_feature_engineer: FeatureEngineer | None = None


def get_feature_engineer(config: FeatureConfig | None = None) -> FeatureEngineer:
    global _feature_engineer
    if _feature_engineer is None or config is not None:
        _feature_engineer = FeatureEngineer(config)
    return _feature_engineer


def build_ml_features(
    df: pd.DataFrame,
    config: FeatureConfig | None = None,
) -> FeatureResult:
    engineer = get_feature_engineer(config)
    return engineer.build_features(df)
