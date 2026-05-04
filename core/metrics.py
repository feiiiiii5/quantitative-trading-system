import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class InstitutionalMetrics:
    cagr: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    calmar_ratio: float = 0.0
    volatility: float = 0.0
    win_rate: float = 0.0
    profit_loss_ratio: float = 0.0
    total_return: float = 0.0
    annual_turnover: float = 0.0
    avg_ic: float = 0.0
    ic_ir: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    information_ratio: float = 0.0
    tracking_error: float = 0.0
    alpha: float = 0.0
    beta: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0
    n_trades: int = 0
    avg_holding_period: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0


def calc_cagr(equity_curve: List[float], n_days: int = None) -> float:
    if len(equity_curve) < 2 or equity_curve[0] <= 0:
        return 0.0
    total_return = equity_curve[-1] / equity_curve[0] - 1
    n_days = n_days or len(equity_curve) - 1
    n_years = max(n_days / 252, 1e-6)
    if total_return <= -1:
        return -1.0
    return float((1 + total_return) ** (1 / n_years) - 1)


def calc_sharpe(returns: pd.Series, risk_free: float = 0.03) -> float:
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free / 252
    std = excess.std()
    if std < 1e-12:
        return 0.0
    return float(excess.mean() / std * np.sqrt(252))


def calc_sortino(returns: pd.Series, risk_free: float = 0.03) -> float:
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free / 252
    downside = excess[excess < 0]
    if len(downside) == 0:
        return float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 1e-12 and excess.mean() > 0 else 0.0
    downside_std = np.sqrt(np.mean(downside ** 2))
    if downside_std < 1e-12:
        return 0.0
    return float(excess.mean() / downside_std * np.sqrt(252))


def calc_max_drawdown(equity_curve: List[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0
    eq = pd.Series(equity_curve)
    cummax = eq.cummax()
    drawdown = (eq - cummax) / cummax
    return float(drawdown.min())


def calc_calmar(cagr: float, max_drawdown: float) -> float:
    if abs(max_drawdown) < 1e-10:
        return 0.0
    return cagr / abs(max_drawdown)


def calc_win_rate(returns: pd.Series) -> float:
    if len(returns) == 0:
        return 0.0
    return float((returns > 0).sum() / len(returns))


def calc_profit_loss_ratio(returns: pd.Series) -> float:
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    if len(losses) == 0:
        return float("inf") if len(wins) > 0 else 0.0
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses.mean())
    if avg_loss < 1e-12:
        return 0.0
    return float(avg_win / avg_loss)


def calc_turnover(positions_history: List[Dict[str, float]], total_equity: float = None) -> float:
    if len(positions_history) < 2:
        return 0.0
    total_turnover = 0.0
    for i in range(1, len(positions_history)):
        prev = positions_history[i - 1]
        curr = positions_history[i]
        all_keys = set(prev.keys()) | set(curr.keys())
        for key in all_keys:
            prev_val = prev.get(key, 0.0)
            curr_val = curr.get(key, 0.0)
            total_turnover += abs(curr_val - prev_val)
    if total_equity and total_equity > 0:
        return total_turnover / (2 * total_equity * len(positions_history))
    return total_turnover


def calc_var(returns: pd.Series, confidence: float = 0.95) -> float:
    if len(returns) < 5:
        return 0.0
    return float(np.percentile(returns, (1 - confidence) * 100))


def calc_cvar(returns: pd.Series, confidence: float = 0.95) -> float:
    if len(returns) < 5:
        return 0.0
    threshold = np.percentile(returns, (1 - confidence) * 100)
    tail = returns[returns <= threshold]
    return float(tail.mean()) if len(tail) > 0 else float(threshold)


def calc_information_ratio(returns: pd.Series, benchmark_returns: pd.Series) -> float:
    if len(returns) < 2 or len(benchmark_returns) < 2:
        return 0.0
    n = min(len(returns), len(benchmark_returns))
    active_return = returns.iloc[-n:] - benchmark_returns.iloc[-n:]
    tracking_error = active_return.std()
    if tracking_error < 1e-12:
        return 0.0
    return float(active_return.mean() / tracking_error * np.sqrt(252))


def calc_alpha_beta(returns: pd.Series, benchmark_returns: pd.Series, risk_free: float = 0.03) -> Tuple:
    if len(returns) < 2 or len(benchmark_returns) < 2:
        return 0.0, 0.0
    n = min(len(returns), len(benchmark_returns))
    r = returns.iloc[-n:].values
    b = benchmark_returns.iloc[-n:].values
    rf_daily = risk_free / 252
    excess_r = r - rf_daily
    excess_b = b - rf_daily
    cov = np.cov(excess_r, excess_b)
    if cov[1, 1] < 1e-12:
        return 0.0, 0.0
    beta = float(cov[0, 1] / cov[1, 1])
    alpha = float(excess_r.mean() - beta * excess_b.mean()) * 252
    return alpha, beta


def calc_max_consecutive(returns: pd.Series, positive: bool = True) -> int:
    max_streak = 0
    current_streak = 0
    for r in returns:
        if (positive and r > 0) or (not positive and r < 0):
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0
    return max_streak


def calc_all_metrics(
    equity_curve: List[float],
    returns: pd.Series = None,
    benchmark_returns: pd.Series = None,
    positions_history: List[Dict[str, float]] = None,
    risk_free: float = 0.03,
) -> InstitutionalMetrics:
    if len(equity_curve) < 2:
        return InstitutionalMetrics()

    eq = pd.Series(equity_curve)
    if returns is None:
        returns = eq.pct_change().dropna()

    cagr = calc_cagr(equity_curve)
    sharpe = calc_sharpe(returns, risk_free)
    sortino = calc_sortino(returns, risk_free)
    max_dd = calc_max_drawdown(equity_curve)
    calmar = calc_calmar(cagr, max_dd)
    vol = float(returns.std() * np.sqrt(252))
    win_rate = calc_win_rate(returns)
    pl_ratio = calc_profit_loss_ratio(returns)
    total_return = float(eq.iloc[-1] / eq.iloc[0] - 1) if eq.iloc[0] > 0 else 0.0
    turnover = calc_turnover(positions_history) if positions_history else 0.0
    var_95 = calc_var(returns)
    cvar_95 = calc_cvar(returns)
    skewness = float(returns.skew()) if len(returns) > 2 else 0.0
    kurtosis = float(returns.kurtosis()) if len(returns) > 2 else 0.0
    max_consec_wins = calc_max_consecutive(returns, True)
    max_consec_losses = calc_max_consecutive(returns, False)

    alpha_val = 0.0
    beta_val = 0.0
    ir = 0.0
    te = 0.0
    if benchmark_returns is not None:
        alpha_val, beta_val = calc_alpha_beta(returns, benchmark_returns, risk_free)
        ir = calc_information_ratio(returns, benchmark_returns)
        n = min(len(returns), len(benchmark_returns))
        active = returns.iloc[-n:] - benchmark_returns.iloc[-n:]
        te = float(active.std() * np.sqrt(252))

    return InstitutionalMetrics(
        cagr=round(cagr, 6),
        sharpe_ratio=round(sharpe, 4),
        sortino_ratio=round(sortino, 4),
        max_drawdown=round(max_dd, 6),
        calmar_ratio=round(calmar, 4),
        volatility=round(vol, 6),
        win_rate=round(win_rate, 4),
        profit_loss_ratio=round(pl_ratio, 4),
        total_return=round(total_return, 6),
        annual_turnover=round(turnover, 6),
        var_95=round(var_95, 6),
        cvar_95=round(cvar_95, 6),
        information_ratio=round(ir, 4),
        tracking_error=round(te, 6),
        alpha=round(alpha_val, 6),
        beta=round(beta_val, 4),
        skewness=round(skewness, 4),
        kurtosis=round(kurtosis, 4),
        n_trades=len(returns),
        max_consecutive_wins=max_consec_wins,
        max_consecutive_losses=max_consec_losses,
    )


def metrics_to_dict(metrics: InstitutionalMetrics) -> Dict:
    return {
        "CAGR": f"{metrics.cagr:.2%}",
        "Sharpe Ratio": f"{metrics.sharpe_ratio:.2f}",
        "Sortino Ratio": f"{metrics.sortino_ratio:.2f}",
        "Max Drawdown": f"{metrics.max_drawdown:.2%}",
        "Calmar Ratio": f"{metrics.calmar_ratio:.2f}",
        "Volatility": f"{metrics.volatility:.2%}",
        "Win Rate": f"{metrics.win_rate:.2%}",
        "Profit/Loss Ratio": f"{metrics.profit_loss_ratio:.2f}",
        "Total Return": f"{metrics.total_return:.2%}",
        "Annual Turnover": f"{metrics.annual_turnover:.2%}",
        "VaR(95%)": f"{metrics.var_95:.4f}",
        "CVaR(95%)": f"{metrics.cvar_95:.4f}",
        "Information Ratio": f"{metrics.information_ratio:.2f}",
        "Tracking Error": f"{metrics.tracking_error:.4f}",
        "Alpha": f"{metrics.alpha:.4f}",
        "Beta": f"{metrics.beta:.2f}",
        "Skewness": f"{metrics.skewness:.2f}",
        "Kurtosis": f"{metrics.kurtosis:.2f}",
        "N Trades": metrics.n_trades,
        "Max Consecutive Wins": metrics.max_consecutive_wins,
        "Max Consecutive Losses": metrics.max_consecutive_losses,
    }
