import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

MIN_BARS_REQUIRED = 10


class InsufficientDataError(ValueError):
    pass


def _vectorized_equity_curve(
    equity: float,
    trades: list[dict],
    n_bars: int,
    entry_indices: list[int],
    exit_indices: list[int],
    pnl_list: list[float],
) -> list[float]:
    """Vectorized equity curve computation for performance.

    This is a fast alternative to the loop-based approach when
    trade data is already computed.
    """
    if n_bars <= 0:
        return [equity]

    equity_curve = [equity] * (n_bars + 1)
    trade_map: dict[int, list[tuple[int, float]]] = {}

    for _idx, (entry, exit_bar, pnl) in enumerate(zip(entry_indices, exit_indices, pnl_list, strict=True)):
        if entry < 0 or entry > n_bars:
            continue
        if entry not in trade_map:
            trade_map[entry] = []
        trade_map[entry].append((exit_bar, pnl))

    for bar in range(1, n_bars + 1):
        cumulative_pnl = 0.0
        closed_trades = []

        if bar in trade_map:
            for exit_bar, pnl in trade_map[bar]:
                if exit_bar <= bar:
                    cumulative_pnl += pnl
                    closed_trades.append((exit_bar, pnl))

        equity_curve[bar] = equity + cumulative_pnl

    return equity_curve


@dataclass
class BacktestResult:
    strategy_name: str
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    calmar_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    avg_profit: float = 0.0
    avg_loss: float = 0.0
    avg_hold_days: float = 0.0
    benchmark_return: float = 0.0
    alpha: float = 0.0
    beta: float = 1.0
    equity_curve: list = field(default_factory=list)
    drawdown_curve: list = field(default_factory=list)
    dates: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    kline_with_signals: list = field(default_factory=list)
    max_points: int = 0
    sortino_ratio: float = 0.0
    max_consecutive_losses: int = 0
    omega_ratio: float = 0.0
    tail_ratio: float = 0.0
    information_ratio: float = 0.0
    recovery_factor: float = 0.0
    avg_mae: float = 0.0
    avg_mfe: float = 0.0
    cvar_95: float = 0.0
    var_95: float = 0.0
    annual_volatility: float = 0.0
    downside_deviation: float = 0.0
    monthly_returns: list = field(default_factory=list)
    monte_carlo: dict = field(default_factory=dict)
    optimization: dict = field(default_factory=dict)
    expectancy: float = 0.0
    payoff_ratio: float = 0.0

    def to_dict(self, max_equity: int = 500, max_trades: int = 200, max_kline: int = 500) -> dict:
        """统一的BacktestResult序列化方法，避免各API端点手动构建dict导致属性名错误"""
        equity_curve = []
        if self.equity_curve and self.dates:
            for i in range(min(len(self.dates), len(self.equity_curve))):
                equity_curve.append({"date": self.dates[i], "value": float(self.equity_curve[i])})
        return {
            "strategy_name": self.strategy_name,
            "total_return": round(self.total_return, 4) if self.total_return else 0,
            "annual_return": round(self.annual_return, 4) if self.annual_return else 0,
            "max_drawdown": round(self.max_drawdown, 4) if self.max_drawdown else 0,
            "sharpe_ratio": self.sharpe_ratio,
            "calmar_ratio": self.calmar_ratio,
            "win_rate": round(self.win_rate, 2) if self.win_rate else 0,
            "profit_factor": self.profit_factor,
            "total_trades": self.total_trades,
            "win_trades": self.win_trades,
            "loss_trades": self.loss_trades,
            "avg_profit": self.avg_profit,
            "avg_loss": self.avg_loss,
            "avg_hold_days": self.avg_hold_days,
            "benchmark_return": round(self.benchmark_return, 4) if self.benchmark_return else 0,
            "alpha": round(self.alpha, 4) if self.alpha else 0,
            "beta": self.beta,
            "sortino_ratio": self.sortino_ratio,
            "max_consecutive_losses": self.max_consecutive_losses,
            "omega_ratio": self.omega_ratio,
            "tail_ratio": self.tail_ratio,
            "information_ratio": self.information_ratio,
            "recovery_factor": self.recovery_factor,
            "avg_mae": self.avg_mae,
            "avg_mfe": self.avg_mfe,
            "expectancy": self.expectancy,
            "payoff_ratio": self.payoff_ratio,
            "cvar_95": self.cvar_95,
            "var_95": self.var_95,
            "annual_volatility": self.annual_volatility,
            "downside_deviation": self.downside_deviation,
            "equity_curve": equity_curve[-max_equity:] if equity_curve else [],
            "drawdown_curve": self.drawdown_curve[-max_equity:] if self.drawdown_curve else [],
            "trades": self.trades[-max_trades:] if self.trades else [],
            "kline_with_signals": self.kline_with_signals[-max_kline:] if self.kline_with_signals else [],
        }

    def summary_dict(self) -> dict:
        """轻量级摘要，用于策略比较等不需要完整曲线的场景"""
        return {
            "strategy_name": self.strategy_name,
            "total_return": round(self.total_return, 4),
            "annual_return": round(self.annual_return, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "max_drawdown": round(self.max_drawdown, 4),
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 2),
            "total_trades": self.total_trades,
            "sortino_ratio": round(self.sortino_ratio, 2),
            "calmar_ratio": round(self.calmar_ratio, 2),
            "omega_ratio": round(self.omega_ratio, 2),
        }

    def downsample_curves(self, max_points: int = 500) -> None:
        if max_points <= 0 or len(self.equity_curve) <= max_points:
            return
        step = len(self.equity_curve) / max_points
        indices = [int(i * step) for i in range(max_points)]
        if indices[-1] != len(self.equity_curve) - 1:
            indices.append(len(self.equity_curve) - 1)
        self.equity_curve = [self.equity_curve[i] for i in indices]
        self.drawdown_curve = [self.drawdown_curve[i] for i in indices]
        self.dates = [self.dates[i] for i in indices]

    def get_performance_summary(self) -> dict:
        """Get a concise performance summary for strategy comparison."""
        return {
            "strategy": self.strategy_name,
            "total_return_pct": round(self.total_return * 100, 2),
            "annual_return_pct": round(self.annual_return * 100, 2),
            "sharpe": round(self.sharpe_ratio, 2),
            "max_drawdown_pct": round(self.max_drawdown * 100, 2),
            "win_rate_pct": round(self.win_rate * 100, 1),
            "total_trades": self.total_trades,
            "calmar": round(self.calmar_ratio, 2),
            "sortino": round(self.sortino_ratio, 2),
            "profit_factor": round(self.profit_factor, 2),
            "avg_mae_pct": round(self.avg_mae, 2) if self.avg_mae else 0,
            "avg_mfe_pct": round(self.avg_mfe, 2) if self.avg_mfe else 0,
        }

    def compare_with(self, other: "BacktestResult") -> dict:
        """Compare this result with another for strategy selection."""
        return {
            "this": self.get_performance_summary(),
            "other": other.get_performance_summary(),
            "sharpe_diff": round(self.sharpe_ratio - other.sharpe_ratio, 2),
            "return_diff_pct": round((self.annual_return - other.annual_return) * 100, 2),
            "drawdown_diff_pct": round((self.max_drawdown - other.max_drawdown) * 100, 2),
            "trade_count_diff": self.total_trades - other.total_trades,
            "recommended": self.strategy_name if self.sharpe_ratio >= other.sharpe_ratio else other.strategy_name,
        }

    def is_better_than(self, other: "BacktestResult", metric: str = "sharpe_ratio") -> bool:
        """Check if this result is better than another on the specified metric."""
        if not isinstance(other, BacktestResult):
            return False
        val_a = float(getattr(self, metric, 0.0) or 0.0)
        val_b = float(getattr(other, metric, 0.0) or 0.0)
        if metric == "max_drawdown":
            return val_a <= val_b
        return val_a >= val_b

    def get_risk_adjusted_metrics(self) -> dict:
        """Calculate comprehensive risk-adjusted performance metrics."""
        metrics = {
            "sharpe": round(self.sharpe_ratio, 2),
            "sortino": round(self.sortino_ratio, 2),
            "calmar": round(self.calmar_ratio, 2),
            "omega": round(self.omega_ratio, 2) if self.omega_ratio else 0,
            "tail_ratio": round(self.tail_ratio, 2) if self.tail_ratio else 0,
            "information_ratio": round(self.information_ratio, 2) if self.information_ratio else 0,
            "var_95": round(self.var_95, 4) if self.var_95 else 0,
            "cvar_95": round(self.cvar_95, 4) if self.cvar_95 else 0,
        }
        recovery = self.recovery_factor if self.recovery_factor else 0
        metrics["recovery_factor"] = round(recovery, 2)
        annualized_vol = self.annual_volatility if self.annual_volatility else 0
        metrics["annual_volatility"] = round(annualized_vol, 4)
        downside = self.downside_deviation if self.downside_deviation else 0
        metrics["downside_deviation"] = round(downside, 4)
        metrics["return_risk_ratio"] = round(self.annual_return / max(annualized_vol, 1e-9), 4)
        metrics["upside_capture_ratio"] = round(
            self.annual_return / max(abs(self.benchmark_return), 1e-9) if self.benchmark_return else 0, 2
        )
        return metrics

    def get_drawdown_analysis(self) -> dict:
        """Detailed drawdown analysis including duration and recovery statistics."""
        if not self.equity_curve or len(self.equity_curve) < 2:
            return {"error": "Insufficient equity curve data"}

        eq = np.array(self.equity_curve, dtype=float)
        peaks = np.maximum.accumulate(eq)
        drawdowns = (peaks - eq) / np.where(peaks > 1e-9, peaks, 1.0) * 100

        in_drawdown = False
        drawdown_periods = []
        current_duration = 0
        max_duration = 0
        drawdown_starts = []

        for i, dd in enumerate(drawdowns):
            if dd > 0.1:
                if not in_drawdown:
                    in_drawdown = True
                    drawdown_starts.append(i)
                current_duration += 1
                max_duration = max(max_duration, current_duration)
            else:
                if in_drawdown:
                    drawdown_periods.append({"duration": current_duration, "start_idx": drawdown_starts[-1], "end_idx": i})
                in_drawdown = False
                current_duration = 0

        if in_drawdown:
            drawdown_periods.append({"duration": current_duration, "start_idx": drawdown_starts[-1] if drawdown_starts else 0, "end_idx": len(drawdowns)})

        avg_duration = float(np.mean([p["duration"] for p in drawdown_periods])) if drawdown_periods else 0
        dd_95 = float(np.percentile(drawdowns, 95)) if len(drawdowns) > 0 else 0

        return {
            "current_drawdown_pct": round(float(drawdowns[-1]) if len(drawdowns) > 0 else 0, 2),
            "max_drawdown_pct": round(float(np.max(drawdowns)), 2),
            "avg_drawdown_pct": round(float(np.mean(drawdowns[drawdowns > 0.1])), 2) if np.any(drawdowns > 0.1) else 0,
            "drawdown_95_pct": round(dd_95, 2),
            "max_drawdown_duration": max_duration,
            "avg_drawdown_duration": round(avg_duration, 1),
            "n_drawdown_periods": len(drawdown_periods),
            "recovered_smoothly": all(p["duration"] < max_duration * 1.5 for p in drawdown_periods) if drawdown_periods else True,
        }

    def get_trade_analysis(self) -> dict:
        """Comprehensive trade-level analysis."""
        sell_trades = [t for t in self.trades if t.get("action") == "sell"]
        if not sell_trades:
            return {"error": "No trades to analyze"}

        pnls = [float(t.get("pnl", 0)) for t in sell_trades]
        maes = [abs(float(t.get("mae", 0))) for t in sell_trades]
        mfes = [float(t.get("mfe", 0)) for t in sell_trades]
        hold_days = [t.get("hold_days", 0) for t in sell_trades]

        pnl_arr = np.array(pnls)
        win_count = int(np.sum(pnl_arr > 0))

        return {
            "total_trades": len(sell_trades),
            "win_rate": round(win_count / len(pnls) * 100, 1) if pnls else 0,
            "avg_pnl": round(float(np.mean(pnl_arr)), 2),
            "median_pnl": round(float(np.median(pnl_arr)), 2),
            "best_trade": round(float(np.max(pnl_arr)), 2),
            "worst_trade": round(float(np.min(pnl_arr)), 2),
            "avg_mae_pct": round(float(np.mean(maes)), 2) if maes else 0,
            "avg_mfe_pct": round(float(np.mean(mfes)), 2) if mfes else 0,
            "mfe_mae_ratio": round(float(np.mean(mfes) / max(np.mean(maes), 1e-9)), 2) if mfes and maes else 0,
            "avg_hold_days": round(float(np.mean(hold_days)), 1) if hold_days else 0,
            "max_hold_days": max(hold_days) if hold_days else 0,
            "profit_factor": round(self.profit_factor, 2) if self.profit_factor else 0,
            "expectancy": round(self.expectancy, 2) if self.expectancy else 0,
            "payoff_ratio": round(self.payoff_ratio, 2) if self.payoff_ratio else 0,
            "consecutive_wins": self._count_max_consecutive(sell_trades, positive=True),
            "consecutive_losses": self._count_max_consecutive(sell_trades, positive=False),
        }

    def _count_max_consecutive(self, trades: list[dict], positive: bool = True) -> int:
        count = 0
        max_count = 0
        for t in trades:
            pnl = t.get("pnl", 0)
            if (positive and pnl > 0) or (not positive and pnl < 0):
                count += 1
                max_count = max(max_count, count)
            else:
                count = 0
        return max_count

    def get_monthly_returns_table(self) -> dict:
        """Monthly returns in a structured table format."""
        if not self.monthly_returns:
            return {"error": "No monthly returns data"}

        monthly = {}
        for entry in self.monthly_returns:
            month = entry.get("month", "")
            ret = entry.get("return", 0)
            monthly[month] = round(ret * 100, 2)

        if not monthly:
            return {"error": "Empty monthly returns"}

        months = sorted(monthly.keys())
        returns = [monthly[m] for m in months]
        positive = sum(1 for r in returns if r > 0)
        negative = sum(1 for r in returns if r < 0)
        best_month = max(returns) if returns else 0
        worst_month = min(returns) if returns else 0

        return {
            "monthly": monthly,
            "months_count": len(months),
            "positive_months": positive,
            "negative_months": negative,
            "win_rate": round(positive / len(months) * 100, 1) if months else 0,
            "best_month": best_month,
            "worst_month": worst_month,
            "avg_monthly_return": round(float(np.mean(returns)), 2) if returns else 0,
        }
