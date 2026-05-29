import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class AttributionResult:
    total_return: float = 0.0
    factor_contributions: dict[str, float] = field(default_factory=dict)
    factor_weights: dict[str, float] = field(default_factory=dict)
    residual: float = 0.0
    r_squared: float = 0.0


class PerformanceAttribution:
    """策略收益归因分析

    将策略收益分解为因子贡献:
    - 市场因子 (Beta): 市场系统性收益贡献
    - 动量因子 (Momentum): 趋势跟踪收益贡献
    - 均值回归因子 (MeanReversion): 反转收益贡献
    - 波动率因子 (Volatility): 波动率收益贡献
    - 残差 (Residual): 无法解释的Alpha
    """

    FACTOR_NAMES = ["market", "momentum", "mean_reversion", "volatility"]

    def __init__(self, lookback: int = 60):
        self._lookback = lookback

    def analyze(
        self,
        strategy_returns: np.ndarray,
        benchmark_returns: np.ndarray,
    ) -> AttributionResult:
        if len(strategy_returns) < 20 or len(benchmark_returns) < 20:
            return AttributionResult()

        min_len = min(len(strategy_returns), len(benchmark_returns))
        sr = strategy_returns[-min_len:]
        br = benchmark_returns[-min_len:]

        if np.std(sr) < 1e-12:
            return AttributionResult(total_return=float(np.sum(sr)))

        factors = self._build_factor_matrix(sr, br)
        contributions = self._regress(sr, factors)

        total = float(np.sum(sr))
        explained = sum(contributions.values())
        residual = total - explained

        weights = {}
        for name, contrib in contributions.items():
            weights[name] = contrib / total if abs(total) > 1e-12 else 0.0

        ss_total = float(np.sum((sr - np.mean(sr)) ** 2))
        ss_residual = float(np.sum((sr - factors @ np.array(list(contributions.values()))) ** 2)) if ss_total > 0 else 0
        r_squared = 1.0 - ss_residual / ss_total if ss_total > 0 else 0.0

        return AttributionResult(
            total_return=round(total, 6),
            factor_contributions={k: round(v, 6) for k, v in contributions.items()},
            factor_weights={k: round(v, 4) for k, v in weights.items()},
            residual=round(residual, 6),
            r_squared=round(max(0, r_squared), 4),
        )

    def _build_factor_matrix(self, sr: np.ndarray, br: np.ndarray) -> np.ndarray:
        n = len(sr)
        market = br.copy()

        momentum = np.zeros(n)
        for i in range(1, n):
            momentum[i] = sr[i - 1]
        momentum[0] = 0.0

        mean_rev = np.zeros(n)
        window = min(5, n)
        for i in range(window, n):
            mean_rev[i] = -np.mean(sr[i - window:i])
        mean_rev[:window] = 0.0

        vol = np.zeros(n)
        vol_window = min(20, n)
        for i in range(vol_window, n):
            vol[i] = np.std(sr[i - vol_window:i])
        vol[:vol_window] = 0.0

        return np.column_stack([market, momentum, mean_rev, vol])

    def _regress(self, y: np.ndarray, x: np.ndarray) -> dict[str, float]:
        try:
            coef, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
            contributions = {}
            for i, name in enumerate(self.FACTOR_NAMES):
                contributions[name] = float(np.sum(x[:, i] * coef[i]))
            return contributions
        except Exception as e:
            logger.debug("归因回归失败: %s", e)
            return dict.fromkeys(self.FACTOR_NAMES, 0.0)

    def analyze_from_series(
        self,
        strategy_returns: pd.Series,
        benchmark_returns: pd.Series,
    ) -> AttributionResult:
        combined = pd.DataFrame({"sr": strategy_returns, "br": benchmark_returns}).dropna()
        sr = combined["sr"].values.astype(float)
        br = combined["br"].values.astype(float)
        return self.analyze(sr, br)

    def rolling_attribution(
        self,
        strategy_returns: np.ndarray,
        benchmark_returns: np.ndarray,
        window: int = 60,
        step: int = 5,
    ) -> list[dict]:
        if len(strategy_returns) < window + 20 or len(benchmark_returns) < window + 20:
            return []

        min_len = min(len(strategy_returns), len(benchmark_returns))
        sr = strategy_returns[-min_len:]
        br = benchmark_returns[-min_len:]

        results = []
        for start in range(0, min_len - window, step):
            end = start + window
            segment_sr = sr[start:end]
            segment_br = br[start:end]
            if np.std(segment_sr) < 1e-12:
                continue
            attr = self.analyze(segment_sr, segment_br)
            results.append({
                "start_idx": start,
                "end_idx": end,
                "total_return": attr.total_return,
                "factor_contributions": attr.factor_contributions,
                "factor_weights": attr.factor_weights,
                "residual": attr.residual,
                "r_squared": attr.r_squared,
            })
        return results

    @staticmethod
    def rolling_sharpe_sortino(
        returns: np.ndarray,
        window: int = 60,
        step: int = 5,
        risk_free_rate: float = 0.0,
        annualize: bool = True,
    ) -> list[dict]:
        if len(returns) < window + 10:
            return []

        r = np.asarray(returns, dtype=float)
        r = r[np.isfinite(r)]
        if len(r) < window + 10:
            return []

        ann_factor = np.sqrt(252) if annualize else 1.0
        results = []

        for start in range(0, len(r) - window, step):
            end = start + window
            seg = r[start:end]
            mean_ret = float(np.mean(seg))
            std_ret = float(np.std(seg, ddof=1)) if len(seg) > 1 else 0.0

            excess_mean = mean_ret - risk_free_rate / 252
            sharpe = (excess_mean / std_ret * ann_factor) if std_ret > 1e-12 else 0.0

            downside = seg[seg < 0]
            downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else (float(np.mean(downside ** 2) ** 0.5) if len(downside) > 0 else 0.0)
            sortino = (excess_mean / downside_std * ann_factor) if downside_std > 1e-12 else 0.0

            cum_ret = float(np.prod(1 + seg) - 1)
            max_dd = 0.0
            peak = 1.0
            equity = 1.0
            for ret in seg:
                equity *= (1 + ret)
                if equity > peak:
                    peak = equity
                dd = (peak - equity) / peak
                if dd > max_dd:
                    max_dd = dd

            calmar = (cum_ret / max_dd * ann_factor) if max_dd > 1e-12 else 0.0

            results.append({
                "start_idx": start,
                "end_idx": end,
                "sharpe_ratio": round(sharpe, 4),
                "sortino_ratio": round(sortino, 4),
                "calmar_ratio": round(calmar, 4),
                "cumulative_return": round(cum_ret, 6),
                "max_drawdown": round(max_dd, 6),
                "volatility": round(std_ret * ann_factor, 6),
            })

        return results
