import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.strategies import BaseStrategy, SignalType

logger = logging.getLogger(__name__)


@dataclass
class SignalQualityReport:
    strategy_name: str
    symbol: str
    total_signals: int = 0
    buy_signals: int = 0
    sell_signals: int = 0
    hold_signals: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    accuracy: float = 0.0
    confusion_matrix: dict = field(default_factory=dict)
    buy_precision: float = 0.0
    buy_recall: float = 0.0
    sell_precision: float = 0.0
    sell_recall: float = 0.0
    avg_signal_return: float = 0.0
    avg_buy_return: float = 0.0
    avg_sell_return: float = 0.0
    win_rate_buy: float = 0.0
    win_rate_sell: float = 0.0
    signal_density: float = 0.0
    holding_period_stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "total_signals": self.total_signals,
            "buy_signals": self.buy_signals,
            "sell_signals": self.sell_signals,
            "hold_signals": self.hold_signals,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "accuracy": round(self.accuracy, 4),
            "confusion_matrix": self.confusion_matrix,
            "buy_precision": round(self.buy_precision, 4),
            "buy_recall": round(self.buy_recall, 4),
            "sell_precision": round(self.sell_precision, 4),
            "sell_recall": round(self.sell_recall, 4),
            "avg_signal_return": round(self.avg_signal_return, 4),
            "avg_buy_return": round(self.avg_buy_return, 4),
            "avg_sell_return": round(self.avg_sell_return, 4),
            "win_rate_buy": round(self.win_rate_buy, 4),
            "win_rate_sell": round(self.win_rate_sell, 4),
            "signal_density": round(self.signal_density, 4),
            "holding_period_stats": self.holding_period_stats,
        }


def evaluate_signal_quality(
    strategy: BaseStrategy,
    df: pd.DataFrame,
    symbol: str = "",
    forward_period: int = 5,
    min_return_threshold: float = 0.005,
) -> SignalQualityReport:
    if df is None or len(df) < forward_period + 10:
        return SignalQualityReport(strategy_name=strategy.name, symbol=symbol)

    df = df.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    if "close" not in df.columns or len(df) < forward_period + 5:
        return SignalQualityReport(strategy_name=strategy.name, symbol=symbol)

    try:
        result = strategy.generate_signals(df)
    except Exception as e:
        logger.warning("Strategy %s signal generation failed: %s", strategy, e)
        return SignalQualityReport(strategy_name=strategy.name, symbol=symbol)

    if not result or not result.signals:
        return SignalQualityReport(strategy_name=strategy.name, symbol=symbol)

    closes = pd.to_numeric(df["close"], errors="coerce").fillna(0).values.astype(float)
    n = len(closes)

    forward_returns = np.zeros(n)
    for i in range(n - forward_period):
        if closes[i] > 0:
            forward_returns[i] = (closes[min(i + forward_period, n - 1)] - closes[i]) / closes[i]

    actual_direction = np.zeros(n, dtype=int)
    actual_direction[forward_returns > min_return_threshold] = 1
    actual_direction[forward_returns < -min_return_threshold] = -1

    predicted_direction = np.zeros(n, dtype=int)
    signal_indices = []
    for sig in result.signals:
        idx = sig.get("bar_index", sig.get("index", -1))
        if 0 <= idx < n:
            signal_indices.append(idx)
            sig_type = sig.get("type", sig.get("signal", SignalType.HOLD))
            if isinstance(sig_type, SignalType):
                if sig_type == SignalType.BUY:
                    predicted_direction[idx] = 1
                elif sig_type == SignalType.SELL:
                    predicted_direction[idx] = -1
            elif isinstance(sig_type, (int, float)):
                if sig_type > 0:
                    predicted_direction[idx] = 1
                elif sig_type < 0:
                    predicted_direction[idx] = -1

    buy_mask = predicted_direction == 1
    sell_mask = predicted_direction == -1
    n_buy = int(buy_mask.sum())
    n_sell = int(sell_mask.sum())
    n_hold = n - n_buy - n_sell

    buy_tp = int(((predicted_direction == 1) & (actual_direction == 1)).sum())
    buy_fp = int(((predicted_direction == 1) & (actual_direction != 1)).sum())
    buy_fn = int(((predicted_direction != 1) & (actual_direction == 1)).sum())

    sell_tp = int(((predicted_direction == -1) & (actual_direction == -1)).sum())
    sell_fp = int(((predicted_direction == -1) & (actual_direction != -1)).sum())
    sell_fn = int(((predicted_direction != -1) & (actual_direction == -1)).sum())

    buy_precision = buy_tp / (buy_tp + buy_fp) if (buy_tp + buy_fp) > 0 else 0
    buy_recall = buy_tp / (buy_tp + buy_fn) if (buy_tp + buy_fn) > 0 else 0
    sell_precision = sell_tp / (sell_tp + sell_fp) if (sell_tp + sell_fp) > 0 else 0
    sell_recall = sell_tp / (sell_tp + sell_fn) if (sell_tp + sell_fn) > 0 else 0

    total_tp = buy_tp + sell_tp
    total_fp = buy_fp + sell_fp
    total_fn = buy_fn + sell_fn
    total_tn = n - total_tp - total_fp - total_fn

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    accuracy = (total_tp + total_tn) / n if n > 0 else 0

    buy_returns = forward_returns[buy_mask]
    sell_returns = -forward_returns[sell_mask]

    avg_buy_ret = float(np.mean(buy_returns)) if len(buy_returns) > 0 else 0
    avg_sell_ret = float(np.mean(sell_returns)) if len(sell_returns) > 0 else 0
    win_rate_buy = float(np.mean(buy_returns > 0)) if len(buy_returns) > 0 else 0
    win_rate_sell = float(np.mean(sell_returns > 0)) if len(sell_returns) > 0 else 0

    holding_periods = []
    buy_indices = sorted([idx for idx in signal_indices if predicted_direction[idx] == 1])
    sell_indices = sorted([idx for idx in signal_indices if predicted_direction[idx] == -1])

    for bi in buy_indices:
        next_sells = [si for si in sell_indices if si > bi]
        if next_sells:
            holding_periods.append(next_sells[0] - bi)

    hp_stats = {}
    if holding_periods:
        hp_stats = {
            "mean": round(float(np.mean(holding_periods)), 1),
            "median": round(float(np.median(holding_periods)), 1),
            "min": int(min(holding_periods)),
            "max": int(max(holding_periods)),
        }

    confusion = {
        "buy": {"tp": buy_tp, "fp": buy_fp, "fn": buy_fn},
        "sell": {"tp": sell_tp, "fp": sell_fp, "fn": sell_fn},
        "overall": {"tp": total_tp, "fp": total_fp, "fn": total_fn, "tn": int(total_tn)},
    }

    signal_density = len(signal_indices) / n if n > 0 else 0

    return SignalQualityReport(
        strategy_name=strategy.name,
        symbol=symbol,
        total_signals=len(signal_indices),
        buy_signals=n_buy,
        sell_signals=n_sell,
        hold_signals=n_hold,
        precision=precision,
        recall=recall,
        f1_score=f1,
        accuracy=accuracy,
        confusion_matrix=confusion,
        buy_precision=buy_precision,
        buy_recall=buy_recall,
        sell_precision=sell_precision,
        sell_recall=sell_recall,
        avg_signal_return=round(float(np.mean(forward_returns[signal_indices])) if signal_indices else 0, 4),
        avg_buy_return=avg_buy_ret,
        avg_sell_return=avg_sell_ret,
        win_rate_buy=win_rate_buy,
        win_rate_sell=win_rate_sell,
        signal_density=signal_density,
        holding_period_stats=hp_stats,
    )
