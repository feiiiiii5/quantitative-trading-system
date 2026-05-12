"""
价格预测模块 - 基于技术分析和统计指标的价格预测
提供多时间尺度的涨跌概率和预期收益率预测
"""
import logging

import numpy as np
import pandas as pd
from scipy import stats

from core.indicators import TechnicalIndicators
from core.ml_utils import optimize_numpy_memory

logger = logging.getLogger(__name__)

HORIZON_MAP = {
    "1d": {"days": 1, "atr_mult": 1.0, "weight_trend": 0.35, "weight_momentum": 0.30},
    "1w": {"days": 5, "atr_mult": 2.24, "weight_trend": 0.30, "weight_momentum": 0.25},
    "1m": {"days": 22, "atr_mult": 4.69, "weight_trend": 0.25, "weight_momentum": 0.20},
    "1y": {"days": 252, "atr_mult": 15.87, "weight_trend": 0.20, "weight_momentum": 0.15},
}


class PricePredictor:

    @staticmethod
    def predict(df: pd.DataFrame, symbol: str) -> dict:
        """
        执行价格预测

        Args:
            df: K线数据DataFrame，需包含close列
            symbol: 股票代码

        Returns:
            包含多时间尺度预测结果的字典
        """
        # 基础校验：数据长度不足返回空预测
        if df is None or len(df) < 60:
            return PricePredictor._empty_prediction()

        # 计算技术指标
        indicators = TechnicalIndicators.compute_all(df)
        if not indicators:
            return PricePredictor._empty_prediction()

        # 提取价格和成交量数据，优化内存使用
        c = optimize_numpy_memory(pd.to_numeric(df["close"], errors="coerce").dropna().values.astype(float))
        v = pd.to_numeric(df["volume"], errors="coerce").dropna().values.astype(float) if "volume" in df.columns else np.ones(len(df))
        v = optimize_numpy_memory(v)

        # 计算各个维度的得分
        trend_score = PricePredictor._trend_momentum_score(c, indicators)
        momentum_score = PricePredictor._overbought_oversold_score(indicators)
        volume_score = PricePredictor._volume_price_score(c, v)
        hurst = PricePredictor._hurst_exponent(c)
        volatility_score = PricePredictor._volatility_score(c, indicators)

        signals = PricePredictor._detect_signals(c, indicators)

        results = {}
        for horizon, cfg in HORIZON_MAP.items():
            wt = cfg["weight_trend"]
            wm = cfg["weight_momentum"]
            wv = 0.20
            wh = 0.10 if hurst > 0.5 else 0.05
            wvol = 0.15
            total = wt + wm + wv + wh + wvol
            composite = (
                wt * trend_score
                + wm * momentum_score
                + wv * volume_score
                + wh * (hurst - 0.5) * 100
                + wvol * volatility_score
            ) / total

            up_prob = PricePredictor._sigmoid(composite / 20)
            down_prob = 1 - up_prob

            atr_val = indicators.get("atr", 0)
            last_close = float(c[-1])
            if atr_val > 0 and last_close > 0:
                expected_range_pct = atr_val * cfg["atr_mult"] / last_close * 100
            else:
                expected_range_pct = abs(composite) * 0.1

            direction = 1 if up_prob > 0.5 else -1
            expected_return = direction * expected_range_pct * abs(up_prob - 0.5) * 2

            confidence = min(abs(up_prob - 0.5) * 200, 95)
            confidence = max(confidence, 10)

            results[horizon] = {
                "up_prob": round(up_prob * 100, 1),
                "down_prob": round(down_prob * 100, 1),
                "expected_return": round(expected_return, 2),
                "range": [
                    round(-expected_range_pct, 2),
                    round(expected_range_pct, 2),
                ],
                "confidence": round(confidence, 1),
                "signals": signals,
            }
        return results

    @staticmethod
    def _trend_momentum_score(c: np.ndarray, ind: dict) -> float:
        """
        计算趋势动量得分

        Args:
            c: 收盘价数组
            ind: 技术指标字典

        Returns:
            趋势得分，正值看多，负值看空
        """
        score = 0
        ma = ind.get("ma", {})

        # MA5 vs MA20
        if 5 in ma and 20 in ma:
            ma5 = ma[5][-1] if ma[5] else 0
            ma20 = ma[20][-1] if ma[20] else 0
            if ma5 > 0 and ma20 > 0:
                score += 20 if ma5 > ma20 else -20
        if 10 in ma and 60 in ma:
            ma10 = ma[10][-1] if ma[10] else 0
            ma60 = ma[60][-1] if ma[60] else 0
            if ma10 > 0 and ma60 > 0:
                score += 15 if ma10 > ma60 else -15
        macd = ind.get("macd", {})
        dif = macd.get("dif", [])
        dea = macd.get("dea", [])
        hist = macd.get("hist", [])
        if dif and dea:
            score += 10 if dif[-1] > dea[-1] else -10
        if len(hist) >= 2:
            score += 5 if hist[-1] > hist[-2] else -5
        st = ind.get("supertrend", {})
        direction = st.get("direction", [])
        if direction:
            score += 15 if direction[-1] == 1 else -15
        return score

    @staticmethod
    def _overbought_oversold_score(ind: dict) -> float:
        """
        计算超买超卖得分

        Args:
            ind: 技术指标字典

        Returns:
            超买超卖得分
        """
        score = 0
        rsi = ind.get("rsi", {})

        # RSI多周期分析
        for p in [6, 12, 24]:
            if p in rsi and rsi[p]:
                val = rsi[p][-1]
                if val > 70:
                    score -= 12
                elif val > 55:
                    score += 6
                elif val < 30:
                    score += 12
                elif val < 45:
                    score -= 6
        kdj = ind.get("kdj", {})
        k = kdj.get("k", [])
        d = kdj.get("d", [])
        j = kdj.get("j", [])
        if k and d:
            score += 5 if k[-1] > d[-1] else -5
            if j:
                if j[-1] > 100:
                    score -= 8
                elif j[-1] < 0:
                    score += 8
        cci_val = ind.get("cci", 0)
        if cci_val > 100:
            score += 5
        elif cci_val < -100:
            score -= 5
        wr_val = ind.get("williams_r", -50)
        if wr_val < -80:
            score += 6
        elif wr_val > -20:
            score -= 6
        return score

    @staticmethod
    def _volume_price_score(c: np.ndarray, v: np.ndarray) -> float:
        """
        计算量价配合得分

        Args:
            c: 收盘价数组
            v: 成交量数组

        Returns:
            量价配合得分
        """
        score = 0
        if len(c) < 5 or len(v) < 5:
            return 0

        # 分析价格上涨/下跌与成交量变化的配合
        price_up = c[-1] > c[-2]
        vol_change = v[-1] / (np.mean(v[-6:-1]) + 1e-10)
        if price_up and vol_change > 1.5:
            score += 15
        elif not price_up and vol_change > 1.5:
            score -= 15
        elif price_up and vol_change < 0.7:
            score -= 5
        elif not price_up and vol_change < 0.7:
            score += 5
        obv = np.cumsum(np.sign(np.diff(c, prepend=c[0])) * v)
        if len(obv) >= 5:
            obv_slope = obv[-1] - obv[-5]
            score += 8 if obv_slope > 0 else -8
        return score

    @staticmethod
    def _hurst_exponent(c: np.ndarray, max_lag: int = 20) -> float:
        """
        计算Hurst指数，用于判断市场的趋势性/均值回归特性

        Args:
            c: 收盘价数组
            max_lag: 最大滞后阶数

        Returns:
            Hurst指数，0.5表示随机游走，>0.5表示趋势性，<0.5表示均值回归
        """
        if len(c) < max_lag * 2:
            return 0.5

        positive = c[c > 0]
        if len(positive) < max_lag * 2:
            return 0.5

        returns = np.diff(np.log(positive))
        if len(returns) < max_lag:
            return 0.5

        if not np.all(np.isfinite(returns)):
            returns = returns[np.isfinite(returns)]
            if len(returns) < max_lag:
                return 0.5

        lags = range(2, max_lag)
        tau = []

        # 计算不同滞后期的标准差
        for lag in lags:
            diff = returns[lag:] - returns[:-lag]
            if len(diff) > 0:
                tau.append(np.std(diff))
            else:
                tau.append(1e-10)
        tau = np.array(tau)
        valid = tau > 0
        if valid.sum() < 3:
            return 0.5
        try:
            log_lags = np.log(np.array(list(lags))[valid])
            log_tau = np.log(tau[valid])
            slope, _, _, _, _ = stats.linregress(log_lags, log_tau)
            return max(0.0, min(1.0, slope / 2))
        except Exception as e:
            logger.debug("Hurst计算失败: %s", e)
            return 0.5

    @staticmethod
    def _volatility_score(c: np.ndarray, ind: dict) -> float:
        """
        计算波动率得分

        Args:
            c: 收盘价数组
            ind: 技术指标字典

        Returns:
            波动率得分
        """
        score = 0
        bb_pos = ind.get("bb_position", 0.5)

        # 布林带位置判断
        if bb_pos > 0.85:
            score -= 8
        elif bb_pos < 0.15:
            score += 8
        boll = ind.get("boll", {})
        width = boll.get("width", [])
        if width and len(width) >= 10:
            current_width = width[-1]
            avg_width = np.mean(width[-10:])
            if current_width < avg_width * 0.5:
                score += 5
            elif current_width > avg_width * 2:
                score -= 5
        return score

    @staticmethod
    def _detect_signals(c: np.ndarray, ind: dict) -> list:
        """
        检测技术指标买卖信号

        Args:
            c: 收盘价数组
            ind: 技术指标字典

        Returns:
            信号列表
        """
        signals = []
        ma = ind.get("ma", {})

        # MA金叉/死叉信号
        if 5 in ma and 20 in ma and len(ma[5]) >= 2 and len(ma[20]) >= 2:
            prev_diff = ma[5][-2] - ma[20][-2]
            curr_diff = ma[5][-1] - ma[20][-1]
            if prev_diff <= 0 and curr_diff > 0:
                signals.append("MA金叉")
            elif prev_diff >= 0 and curr_diff < 0:
                signals.append("MA死叉")
        rsi = ind.get("rsi", {})
        if 6 in rsi and rsi[6]:
            val = rsi[6][-1]
            if val < 30:
                signals.append("RSI超卖")
            elif val > 70:
                signals.append("RSI超买")
        macd = ind.get("macd", {})
        hist = macd.get("hist", [])
        if len(hist) >= 2:
            if hist[-2] < 0 and hist[-1] > 0:
                signals.append("MACD金叉")
            elif hist[-2] > 0 and hist[-1] < 0:
                signals.append("MACD死叉")
        kdj = ind.get("kdj", {})
        k = kdj.get("k", [])
        d = kdj.get("d", [])
        if k and d and len(k) >= 2:
            if k[-2] < d[-2] and k[-1] > d[-1]:
                signals.append("KDJ金叉")
            elif k[-2] > d[-2] and k[-1] < d[-1]:
                signals.append("KDJ死叉")
        st = ind.get("supertrend", {})
        direction = st.get("direction", [])
        if len(direction) >= 2:
            if direction[-2] == -1 and direction[-1] == 1:
                signals.append("趋势转多")
            elif direction[-2] == 1 and direction[-1] == -1:
                signals.append("趋势转空")
        return signals[:6]

    @staticmethod
    def _sigmoid(x: float) -> float:
        """
        Sigmoid激活函数，用于将得分转换为概率

        Args:
            x: 输入值

        Returns:
            0-1之间的概率值
        """
        x = max(-10, min(10, x))  # 防止溢出
        return 1 / (1 + np.exp(-x))

    @staticmethod
    def _empty_prediction() -> dict:
        """
        创建空预测结果（用于数据不足时）

        Returns:
            空预测字典
        """
        result = {}
        for horizon in HORIZON_MAP:
            result[horizon] = {
                "up_prob": 50.0,
                "down_prob": 50.0,
                "expected_return": 0.0,
                "range": [0.0, 0.0],
                "confidence": 0.0,
                "signals": [],
            }
        return result
