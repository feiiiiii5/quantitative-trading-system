import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class SeasonalReport:
    symbol: str
    period: str
    monthly_returns: dict = field(default_factory=dict)
    day_of_week_returns: dict = field(default_factory=dict)
    best_month: str = ""
    worst_month: str = ""
    best_day: str = ""
    worst_day: str = ""
    monthly_sharpe: dict = field(default_factory=dict)
    turn_of_month_effect: dict = field(default_factory=dict)
    holiday_effect: dict = field(default_factory=dict)
    seasonality_strength: float = 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "period": self.period,
            "monthly_returns": self.monthly_returns,
            "day_of_week_returns": self.day_of_week_returns,
            "best_month": self.best_month,
            "worst_month": self.worst_month,
            "best_day": self.best_day,
            "worst_day": self.worst_day,
            "monthly_sharpe": self.monthly_sharpe,
            "turn_of_month_effect": self.turn_of_month_effect,
            "seasonality_strength": round(self.seasonality_strength, 4),
        }


_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def analyze_seasonality(
    df: pd.DataFrame,
    symbol: str = "",
    period: str = "1y",
) -> SeasonalReport:
    if df is None or len(df) < 30:
        return SeasonalReport(symbol=symbol, period=period)

    df = df.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])

    if "close" not in df.columns or len(df) < 20:
        return SeasonalReport(symbol=symbol, period=period)

    closes = pd.to_numeric(df["close"], errors="coerce").dropna().values.astype(float)
    dates = df["date"].values if "date" in df.columns else None

    returns = np.diff(closes) / np.where(closes[:-1] > 0, closes[:-1], 1)
    if len(returns) < 10:
        return SeasonalReport(symbol=symbol, period=period)

    report = SeasonalReport(symbol=symbol, period=period)

    if dates is not None and len(dates) > len(returns):
        dates = dates[1:]
    elif dates is not None and len(dates) < len(returns):
        returns = returns[:len(dates)]

    if dates is not None and len(dates) == len(returns):
        dt_index = pd.DatetimeIndex(dates)

        monthly_groups: dict[int, list[float]] = {}
        for i, dt in enumerate(dt_index):
            month = dt.month
            monthly_groups.setdefault(month, []).append(returns[i])

        monthly_returns = {}
        monthly_sharpe = {}
        for month in range(1, 13):
            if month in monthly_groups:
                rets = np.array(monthly_groups[month])
                monthly_returns[_MONTH_NAMES[month - 1]] = round(float(np.mean(rets)) * 100, 2)
                if np.std(rets) > 0:
                    monthly_sharpe[_MONTH_NAMES[month - 1]] = round(
                        float(np.mean(rets) / np.std(rets) * np.sqrt(252)), 4
                    )
                else:
                    monthly_sharpe[_MONTH_NAMES[month - 1]] = 0.0

        report.monthly_returns = monthly_returns
        report.monthly_sharpe = monthly_sharpe

        if monthly_returns:
            best = max(monthly_returns.items(), key=lambda x: x[1])[0]
            worst = min(monthly_returns.items(), key=lambda x: x[1])[0]
            report.best_month = best
            report.worst_month = worst

        dow_groups: dict[int, list[float]] = {}
        for i, dt in enumerate(dt_index):
            dow = dt.dayofweek
            if dow < 5:
                dow_groups.setdefault(dow, []).append(returns[i])

        dow_returns = {}
        for dow in range(5):
            if dow in dow_groups:
                rets = np.array(dow_groups[dow])
                dow_returns[_DAY_NAMES[dow]] = round(float(np.mean(rets)) * 100, 4)

        report.day_of_week_returns = dow_returns

        if dow_returns:
            best_dow = max(dow_returns.items(), key=lambda x: x[1])[0]
            worst_dow = min(dow_returns.items(), key=lambda x: x[1])[0]
            report.best_day = best_dow
            report.worst_day = worst_dow

        tom_returns = []
        non_tom_returns = []
        for i, dt in enumerate(dt_index):
            day = dt.day
            if day <= 3 or day >= 28:
                tom_returns.append(returns[i])
            else:
                non_tom_returns.append(returns[i])

        if tom_returns and non_tom_returns:
            report.turn_of_month_effect = {
                "tom_avg_return": round(float(np.mean(tom_returns)) * 100, 4),
                "non_tom_avg_return": round(float(np.mean(non_tom_returns)) * 100, 4),
                "tom_win_rate": round(float(np.mean(np.array(tom_returns) > 0)), 4),
                "non_tom_win_rate": round(float(np.mean(np.array(non_tom_returns) > 0)), 4),
            }

    if monthly_returns:
        values = list(monthly_returns.values())
        if len(values) >= 3:
            spread = max(values) - min(values)
            overall_avg = float(np.mean(values))
            if overall_avg != 0:
                report.seasonality_strength = min(1.0, abs(spread / (abs(overall_avg) + 0.01)))
            else:
                report.seasonality_strength = min(1.0, abs(spread) / 1.0)

    return report
