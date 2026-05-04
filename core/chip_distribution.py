"""
QuantCore 筹码分布模块
对标同花顺筹码分布：成本分布、获利比例、筹码集中度、支撑阻力位
基于成交量分布模型计算筹码分布
"""
import logging
import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ChipDistribution:
    prices: list[float]
    distribution: list[float]
    avg_cost: float
    profit_ratio: float
    concentration: float
    support_price: float
    resistance_price: float
    peak_price: float
    chip_bands: list[dict]


def _volume_profile_distribution(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray,
    n_bins: int = 80,
    decay: float = 0.97,
) -> tuple[np.ndarray, np.ndarray]:
    if len(close) < 10:
        return np.array([]), np.array([])

    all_low = float(np.min(low))
    all_high = float(np.max(high))
    if all_high <= all_low:
        return np.array([]), np.array([])

    price_bins = np.linspace(all_low, all_high, n_bins + 1)
    bin_centers = (price_bins[:-1] + price_bins[1:]) / 2
    distribution = np.zeros(n_bins)

    n = len(close)
    for i in range(n):
        bar_low = float(low[i])
        bar_high = float(high[i])
        bar_vol = float(volume[i])
        if bar_high <= bar_low or bar_vol <= 0:
            continue

        weight = decay ** (n - 1 - i)

        for j in range(n_bins):
            bin_low = price_bins[j]
            bin_high = price_bins[j + 1]
            overlap_low = max(bin_low, bar_low)
            overlap_high = min(bin_high, bar_high)
            if overlap_high > overlap_low:
                overlap_ratio = (overlap_high - overlap_low) / (bar_high - bar_low)
                distribution[j] += bar_vol * overlap_ratio * weight

    total = distribution.sum()
    if total > 0:
        distribution = distribution / total

    return bin_centers, distribution


class ChipDistributionAnalyzer:
    """筹码分布分析器"""

    def __init__(self, n_bins: int = 80, decay: float = 0.97):
        self._n_bins = n_bins
        self._decay = decay

    def analyze(
        self,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
        current_price: Optional[float] = None,
    ) -> ChipDistribution:
        if len(close) < 10:
            return ChipDistribution(
                prices=[], distribution=[], avg_cost=0, profit_ratio=0,
                concentration=0, support_price=0, resistance_price=0,
                peak_price=0, chip_bands=[],
            )

        if current_price is None:
            current_price = float(close[-1])

        prices, distribution = _volume_profile_distribution(
            close, high, low, volume, self._n_bins, self._decay
        )

        if len(prices) == 0:
            return ChipDistribution(
                prices=[], distribution=[], avg_cost=0, profit_ratio=0,
                concentration=0, support_price=0, resistance_price=0,
                peak_price=0, chip_bands=[],
            )

        avg_cost = float(np.average(prices, weights=distribution))

        profit_mask = prices <= current_price
        profit_ratio = float(distribution[profit_mask].sum()) if distribution[profit_mask].sum() > 0 else 0.0

        sorted_idx = np.argsort(distribution)[::-1]
        top_70_pct = 0.0
        concentration_range = 0.0
        cumsum = 0.0
        peak_prices = []
        for idx in sorted_idx:
            cumsum += distribution[idx]
            peak_prices.append(prices[idx])
            if cumsum >= 0.7:
                concentration_range = float(max(peak_prices) - min(peak_prices))
                break

        price_range = float(prices[-1] - prices[0])
        concentration = 1.0 - (concentration_range / price_range) if price_range > 0 else 0.5

        peak_idx = int(np.argmax(distribution))
        peak_price = float(prices[peak_idx])

        support_idx = 0
        for i in range(peak_idx - 1, -1, -1):
            if distribution[i] < distribution[peak_idx] * 0.1:
                support_idx = i
                break
        support_price = float(prices[support_idx])

        resistance_idx = len(prices) - 1
        for i in range(peak_idx + 1, len(prices)):
            if distribution[i] < distribution[peak_idx] * 0.1:
                resistance_idx = i
                break
        resistance_price = float(prices[resistance_idx])

        chip_bands = []
        band_edges = [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0]
        for k in range(len(band_edges) - 1):
            low_pct = band_edges[k]
            high_pct = band_edges[k + 1]
            band_mask = (distribution >= low_pct * distribution.max()) & (distribution <= high_pct * distribution.max())
            if band_mask.any():
                band_prices = prices[band_mask]
                band_dist = distribution[band_mask]
                chip_bands.append({
                    "range": f"{low_pct*100:.0f}%-{high_pct*100:.0f}%",
                    "price_low": round(float(band_prices.min()), 2),
                    "price_high": round(float(band_prices.max()), 2),
                    "weight": round(float(band_dist.sum()), 4),
                })

        return ChipDistribution(
            prices=[round(float(p), 2) for p in prices],
            distribution=[round(float(d), 6) for d in distribution],
            avg_cost=round(avg_cost, 2),
            profit_ratio=round(profit_ratio, 4),
            concentration=round(concentration, 4),
            support_price=round(support_price, 2),
            resistance_price=round(resistance_price, 2),
            peak_price=round(peak_price, 2),
            chip_bands=chip_bands,
        )

    def compute_chip_fire(self, close: np.ndarray, high: np.ndarray, low: np.ndarray, volume: np.ndarray) -> dict:
        if len(close) < 30:
            return {"status": "insufficient_data"}

        n = len(close)
        current_price = float(close[-1])

        short_chip = self.analyze(close[-30:], high[-30:], low[-30:], volume[-30:], current_price)
        mid_chip = self.analyze(close[-60:], high[-60:], low[-60:], volume[-60:], current_price) if n >= 60 else short_chip
        long_chip = self.analyze(close[-120:], high[-120:], low[-120:], volume[-120:], current_price) if n >= 120 else mid_chip

        short_conc = short_chip.concentration
        mid_conc = mid_chip.concentration
        long_conc = long_chip.concentration

        if short_conc > 0.7 and mid_conc > 0.6:
            status = "highly_concentrated"
            signal = "筹码高度集中，关注突破方向"
        elif short_conc > 0.5 and current_price > short_chip.avg_cost:
            status = "concentrated_above_cost"
            signal = "筹码集中且在成本线上方，偏多"
        elif short_conc > 0.5 and current_price < short_chip.avg_cost:
            status = "concentrated_below_cost"
            signal = "筹码集中但在成本线下方，偏空"
        elif short_conc < 0.3:
            status = "dispersed"
            signal = "筹码分散，方向不明"
        else:
            status = "moderate"
            signal = "筹码分布适中"

        return {
            "status": status,
            "signal": signal,
            "short_concentration": round(short_conc, 4),
            "mid_concentration": round(mid_conc, 4),
            "long_concentration": round(long_conc, 4),
            "avg_cost_short": short_chip.avg_cost,
            "avg_cost_mid": mid_chip.avg_cost,
            "avg_cost_long": long_chip.avg_cost,
            "profit_ratio": short_chip.profit_ratio,
            "support": short_chip.support_price,
            "resistance": short_chip.resistance_price,
        }


_analyzer: Optional[ChipDistributionAnalyzer] = None
_analyzer_lock = threading.Lock()


def get_chip_analyzer() -> ChipDistributionAnalyzer:
    global _analyzer
    if _analyzer is None:
        with _analyzer_lock:
            if _analyzer is None:
                _analyzer = ChipDistributionAnalyzer()
    return _analyzer
