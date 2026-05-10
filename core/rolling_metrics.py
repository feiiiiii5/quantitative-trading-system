import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class RollingMetricsTracker:
    """滚动绩效指标追踪器，实时计算滚动Sharpe/Sortino/Calmar/信息比率"""

    def __init__(self, risk_free_rate: float = 0.03, annualize_factor: int = 252):
        self._rf = risk_free_rate
        self._ann = annualize_factor

    def compute_rolling_sharpe(
        self,
        returns: pd.Series,
        window: int = 60,
    ) -> dict:
        """计算滚动Sharpe比率

        Args:
            returns: 日收益率序列
            window: 滚动窗口（交易日）

        Returns:
            滚动Sharpe时间序列和统计摘要
        """
        if len(returns) < window + 5:
            return {"error": f"数据不足: 需要{window + 5}个点，实际{len(returns)}"}

        daily_rf = self._rf / self._ann
        excess = returns - daily_rf
        rolling_mean = excess.rolling(window).mean()
        rolling_std = excess.rolling(window).std()
        rolling_sharpe = (rolling_mean / rolling_std.replace(0, np.nan)) * np.sqrt(self._ann)
        rolling_sharpe = rolling_sharpe.dropna()

        # 降采样
        max_points = 200
        if len(rolling_sharpe) > max_points:
            step = len(rolling_sharpe) / max_points
            indices = [int(i * step) for i in range(max_points)]
            if indices[-1] != len(rolling_sharpe) - 1:
                indices.append(len(rolling_sharpe) - 1)
            rolling_sharpe = rolling_sharpe.iloc[indices]

        dates = [str(d)[:10] for d in rolling_sharpe.index]
        values = [round(float(v), 4) if np.isfinite(v) else None for v in rolling_sharpe.values]
        valid_values = [v for v in values if v is not None]

        current = valid_values[-1] if valid_values else None
        # Sharpe状态分类
        if current is None:
            regime = "unknown"
        elif current > 2.0:
            regime = "excellent"
        elif current > 1.0:
            regime = "good"
        elif current > 0.0:
            regime = "marginal"
        else:
            regime = "poor"

        return {
            "dates": dates,
            "values": values,
            "current": current,
            "mean": round(float(np.mean(valid_values)), 4) if valid_values else None,
            "std": round(float(np.std(valid_values)), 4) if valid_values else None,
            "min": round(float(np.min(valid_values)), 4) if valid_values else None,
            "max": round(float(np.max(valid_values)), 4) if valid_values else None,
            "regime": regime,
            "window": window,
            "annualized": True,
        }

    def compute_rolling_sortino(
        self,
        returns: pd.Series,
        window: int = 60,
    ) -> dict:
        """计算滚动Sortino比率

        Args:
            returns: 日收益率序列
            window: 滚动窗口

        Returns:
            滚动Sortino时间序列
        """
        if len(returns) < window + 5:
            return {"error": f"数据不足: 需要{window + 5}个点，实际{len(returns)}"}

        daily_rf = self._rf / self._ann

        excess = returns - daily_rf
        downside = excess.clip(upper=0)
        rolling_excess_mean = excess.rolling(window).mean()
        rolling_downside_dev = downside.rolling(window).apply(
            lambda x: np.sqrt(np.mean(x ** 2)), raw=True
        )
        result = (rolling_excess_mean / rolling_downside_dev.replace(0, np.nan)) * np.sqrt(self._ann)
        result = result.dropna()

        max_points = 200
        if len(result) > max_points:
            step = len(result) / max_points
            indices = [int(i * step) for i in range(max_points)]
            if indices[-1] != len(result) - 1:
                indices.append(len(result) - 1)
            result = result.iloc[indices]

        dates = [str(d)[:10] for d in result.index]
        values = [round(float(v), 4) if np.isfinite(v) else None for v in result.values]
        valid_values = [v for v in values if v is not None]

        return {
            "dates": dates,
            "values": values,
            "current": valid_values[-1] if valid_values else None,
            "mean": round(float(np.mean(valid_values)), 4) if valid_values else None,
            "window": window,
        }

    def compute_rolling_calmar(
        self,
        equity_curve: pd.Series,
        window: int = 120,
    ) -> dict:
        """计算滚动Calmar比率（年化收益/最大回撤）

        Args:
            equity_curve: 权益曲线
            window: 滚动窗口

        Returns:
            滚动Calmar时间序列
        """
        if len(equity_curve) < window + 5:
            return {"error": f"数据不足: 需要{window + 5}个点，实际{len(equity_curve)}"}

        eq_vals = equity_curve.values.astype(float)
        n = len(eq_vals)

        rolling_start = eq_vals[:n - window + 1] if n >= window else eq_vals[:1]
        rolling_end = eq_vals[window - 1:] if n >= window else eq_vals[-1:]

        total_ret = rolling_end / np.where(rolling_start > 0, rolling_start, np.nan) - 1
        ann_ret = np.power(1 + np.nan_to_num(total_ret, nan=0), self._ann / window) - 1

        max_dd_arr = np.full(n - window + 1, np.nan)
        for i in range(n - window + 1):
            w = eq_vals[i:i + window]
            peak = np.maximum.accumulate(w)
            dd = (w - peak) / np.where(peak > 0, peak, np.nan)
            min_dd = np.nanmin(dd)
            max_dd_arr[i] = abs(min_dd) if np.isfinite(min_dd) else 0

        calmar = np.where(max_dd_arr > 1e-8, ann_ret[:len(max_dd_arr)] / max_dd_arr, np.nan)
        result = pd.Series(calmar, index=equity_curve.index[window - 1:], dtype=float)
        result = result.dropna()

        max_points = 200
        if len(result) > max_points:
            step = len(result) / max_points
            indices = [int(i * step) for i in range(max_points)]
            if indices[-1] != len(result) - 1:
                indices.append(len(result) - 1)
            result = result.iloc[indices]

        dates = [str(d)[:10] for d in result.index]
        values = [round(float(v), 4) if np.isfinite(v) else None for v in result.values]
        valid_values = [v for v in values if v is not None]

        return {
            "dates": dates,
            "values": values,
            "current": valid_values[-1] if valid_values else None,
            "mean": round(float(np.mean(valid_values)), 4) if valid_values else None,
            "window": window,
        }

    def compute_information_ratio(
        self,
        returns: pd.Series,
        benchmark_returns: pd.Series,
        window: int = 60,
    ) -> dict:
        """计算滚动信息比率

        Args:
            returns: 策略日收益率
            benchmark_returns: 基准日收益率
            window: 滚动窗口

        Returns:
            滚动IR时间序列
        """
        common_idx = returns.index.intersection(benchmark_returns.index)
        if len(common_idx) < window + 5:
            return {"error": f"重叠数据不足: 需要{window + 5}个点"}

        r = returns.loc[common_idx]
        b = benchmark_returns.loc[common_idx]
        active = r - b

        rolling_active_mean = active.rolling(window).mean()
        rolling_tracking_error = active.rolling(window).std()
        rolling_ir = (rolling_active_mean / rolling_tracking_error.replace(0, np.nan)) * np.sqrt(self._ann)
        rolling_ir = rolling_ir.dropna()

        max_points = 200
        if len(rolling_ir) > max_points:
            step = len(rolling_ir) / max_points
            indices = [int(i * step) for i in range(max_points)]
            if indices[-1] != len(rolling_ir) - 1:
                indices.append(len(rolling_ir) - 1)
            rolling_ir = rolling_ir.iloc[indices]

        dates = [str(d)[:10] for d in rolling_ir.index]
        values = [round(float(v), 4) if np.isfinite(v) else None for v in rolling_ir.values]
        valid_values = [v for v in values if v is not None]

        return {
            "dates": dates,
            "values": values,
            "current": valid_values[-1] if valid_values else None,
            "mean": round(float(np.mean(valid_values)), 4) if valid_values else None,
            "window": window,
        }

    def compute_all_rolling_metrics(
        self,
        returns: pd.Series,
        benchmark_returns: pd.Series | None = None,
        equity_curve: pd.Series | None = None,
    ) -> dict:
        """一次性计算所有滚动指标

        Args:
            returns: 策略日收益率
            benchmark_returns: 可选基准收益率
            equity_curve: 可选权益曲线

        Returns:
            所有滚动指标的汇总
        """
        result: dict[str, Any] = {}
        result["sharpe"] = self.compute_rolling_sharpe(returns)
        result["sortino"] = self.compute_rolling_sortino(returns)

        if equity_curve is not None and len(equity_curve) > 125:
            result["calmar"] = self.compute_rolling_calmar(equity_curve)

        if benchmark_returns is not None:
            result["information_ratio"] = self.compute_information_ratio(returns, benchmark_returns)

        # 综合评分
        sharpe_val = result["sharpe"].get("current")
        sortino_val = result["sortino"].get("current")
        if sharpe_val is not None and sortino_val is not None:
            composite = (sharpe_val * 0.5 + sortino_val * 0.3)
            if "calmar" in result and result["calmar"].get("current") is not None:
                composite += result["calmar"]["current"] * 0.2
            result["composite_score"] = round(composite, 4)
            result["performance_regime"] = (
                "excellent" if composite > 2.0 else
                "good" if composite > 1.0 else
                "marginal" if composite > 0.0 else
                "poor"
            )

        return result


_tracker: RollingMetricsTracker | None = None


def get_rolling_metrics_tracker() -> RollingMetricsTracker:
    global _tracker
    if _tracker is None:
        _tracker = RollingMetricsTracker()
    return _tracker
