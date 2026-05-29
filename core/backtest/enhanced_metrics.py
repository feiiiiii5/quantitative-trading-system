from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ReturnMetrics:
    total_return: float = 0.0
    cagr: float = 0.0
    buy_hold_return: float = 0.0
    alpha: float = 0.0
    exposure_time_pct: float = 0.0


@dataclass
class RiskMetrics:
    max_drawdown: float = 0.0
    max_drawdown_duration_days: int = 0
    avg_drawdown: float = 0.0
    annual_volatility: float = 0.0
    downside_deviation: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0


@dataclass
class RiskAdjustedMetrics:
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    omega_ratio: float = 0.0
    profit_factor: float = 0.0


@dataclass
class TradeStatistics:
    total_trades: int = 0
    win_rate: float = 0.0
    avg_win_avg_loss: float = 0.0
    expectancy: float = 0.0
    avg_trade_duration: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    trades_per_year: float = 0.0


@dataclass
class DistributionAnalysis:
    skewness: float = 0.0
    kurtosis: float = 0.0
    tail_ratio: float = 0.0
    monthly_return_heatmap: dict = field(default_factory=dict)
    return_histogram: dict = field(default_factory=dict)


@dataclass
class ComprehensiveMetrics:
    returns: ReturnMetrics = field(default_factory=ReturnMetrics)
    risk: RiskMetrics = field(default_factory=RiskMetrics)
    risk_adjusted: RiskAdjustedMetrics = field(default_factory=RiskAdjustedMetrics)
    trades: TradeStatistics = field(default_factory=TradeStatistics)
    distribution: DistributionAnalysis = field(default_factory=DistributionAnalysis)
    guardrail_warnings: list[str] = field(default_factory=list)


def compute_comprehensive_metrics(
    equity_curve: list[float],
    dates: list[str],
    trades: list[dict],
    initial_capital: float = 1_000_000,
    benchmark_returns: list[float] | None = None,
    risk_free_rate: float = 0.02,
    n_params: int = 0,
) -> ComprehensiveMetrics:
    if not equity_curve or len(equity_curve) < 2:
        return ComprehensiveMetrics(guardrail_warnings=["权益曲线数据不足"])

    eq = np.array(equity_curve, dtype=float)
    n = len(eq)
    returns = np.diff(eq) / np.where(eq[:-1] > 1e-9, eq[:-1], 1.0)

    trading_days = max(n - 1, 1)
    years = trading_days / 252

    total_return = (eq[-1] / eq[0] - 1.0) if eq[0] > 1e-9 else 0.0
    cagr = ((eq[-1] / eq[0]) ** (1 / max(years, 1e-9)) - 1) if eq[0] > 1e-9 and years > 0 else 0.0

    buy_hold = 0.0
    if benchmark_returns is not None and len(benchmark_returns) > 0:
        buy_hold = float(np.prod(1 + np.array(benchmark_returns)) - 1)
    alpha = cagr - (buy_hold / max(years, 1e-9) if years > 0 else 0)

    sell_trades = [t for t in trades if t.get("action") == "sell"]
    in_position_bars = 0
    if sell_trades:
        entry_bars = set()
        exit_bars = set()
        for t in trades:
            idx = t.get("bar_index", 0)
            if t.get("action") == "buy":
                entry_bars.add(idx)
            elif t.get("action") == "sell":
                exit_bars.add(idx)
        in_position_bars = len(entry_bars | exit_bars)
    exposure = min(in_position_bars / max(trading_days, 1) * 100, 100.0)

    ret_metrics = ReturnMetrics(
        total_return=round(total_return, 6),
        cagr=round(cagr, 6),
        buy_hold_return=round(buy_hold, 6),
        alpha=round(alpha, 6),
        exposure_time_pct=round(exposure, 1),
    )

    peak = np.maximum.accumulate(eq)
    dd = np.where(peak > 1e-9, (peak - eq) / peak, 0.0)
    max_dd = float(np.max(dd))

    dd_periods = []
    in_dd = False
    start = 0
    for i, d in enumerate(dd):
        if d > 1e-6:
            if not in_dd:
                in_dd = True
                start = i
        else:
            if in_dd:
                dd_periods.append((start, i, float(np.max(dd[start:i+1]))))
                in_dd = False
    if in_dd:
        dd_periods.append((start, len(dd) - 1, float(np.max(dd[start:]))))

    max_dd_duration = max((p[1] - p[0] for p in dd_periods), default=0)
    avg_dd = float(np.mean([p[2] for p in dd_periods])) if dd_periods else 0.0

    ann_vol = float(np.std(returns) * np.sqrt(252)) if len(returns) > 1 else 0.0
    neg_returns = returns[returns < 0]
    downside_dev = float(np.sqrt(np.mean(neg_returns ** 2)) * np.sqrt(252)) if len(neg_returns) > 0 else 0.0
    var_95 = float(np.percentile(returns, 5)) if len(returns) > 1 else 0.0
    cvar_95 = float(np.mean(returns[returns <= var_95])) if len(returns[returns <= var_95]) > 0 else var_95

    risk_metrics = RiskMetrics(
        max_drawdown=round(max_dd, 6),
        max_drawdown_duration_days=int(max_dd_duration),
        avg_drawdown=round(avg_dd, 6),
        annual_volatility=round(ann_vol, 6),
        downside_deviation=round(downside_dev, 6),
        var_95=round(var_95, 6),
        cvar_95=round(cvar_95, 6),
    )

    sharpe = ((np.mean(returns) - risk_free_rate / 252) / np.std(returns) * np.sqrt(252)) if np.std(returns) > 1e-12 else 0.0
    sortino = ((np.mean(returns) - risk_free_rate / 252) / downside_dev * np.sqrt(252)) if downside_dev > 1e-12 else 0.0
    calmar = (cagr / max_dd) if max_dd > 1e-9 else 0.0

    threshold = risk_free_rate / 252
    gains = returns[returns > threshold] - threshold
    losses = threshold - returns[returns < threshold]
    omega = float(np.sum(gains) / np.sum(losses)) if np.sum(losses) > 1e-12 else 999.0

    total_win = sum(float(t.get("pnl", 0)) for t in sell_trades if float(t.get("pnl", 0)) > 0)
    total_loss = sum(abs(float(t.get("pnl", 0))) for t in sell_trades if float(t.get("pnl", 0)) < 0)
    profit_factor = total_win / max(total_loss, 1e-9) if total_loss > 0 else (999.0 if total_win > 0 else 0.0)

    risk_adj = RiskAdjustedMetrics(
        sharpe_ratio=round(float(sharpe), 4),
        sortino_ratio=round(float(sortino), 4),
        calmar_ratio=round(float(calmar), 4),
        omega_ratio=round(omega, 4),
        profit_factor=round(profit_factor, 4),
    )

    n_trades = len(sell_trades)
    win_trades = [t for t in sell_trades if float(t.get("pnl", 0)) > 0]
    loss_trades = [t for t in sell_trades if float(t.get("pnl", 0)) < 0]
    win_rate = len(win_trades) / max(n_trades, 1)
    avg_win = float(np.mean([float(t.get("pnl", 0)) for t in win_trades])) if win_trades else 0.0
    avg_loss = float(np.mean([abs(float(t.get("pnl", 0))) for t in loss_trades])) if loss_trades else 1e-9
    payoff = avg_win / max(avg_loss, 1e-9)
    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss
    hold_days = [float(t.get("hold_days", 0)) for t in sell_trades if t.get("hold_days")]
    avg_duration = float(np.mean(hold_days)) if hold_days else 0.0
    tpy = n_trades / max(years, 1e-9) if years > 0 else 0.0

    def _max_consecutive(trade_list: list[dict], positive: bool) -> int:
        count = 0
        best = 0
        for t in trade_list:
            pnl = float(t.get("pnl", 0))
            if (positive and pnl > 0) or (not positive and pnl < 0):
                count += 1
                best = max(best, count)
            else:
                count = 0
        return best

    trade_stats = TradeStatistics(
        total_trades=n_trades,
        win_rate=round(win_rate, 4),
        avg_win_avg_loss=round(payoff, 4),
        expectancy=round(expectancy, 2),
        avg_trade_duration=round(avg_duration, 1),
        max_consecutive_wins=_max_consecutive(sell_trades, True),
        max_consecutive_losses=_max_consecutive(sell_trades, False),
        trades_per_year=round(tpy, 1),
    )

    skew = float(pd.Series(returns).skew()) if len(returns) > 2 else 0.0
    kurt = float(pd.Series(returns).kurtosis()) if len(returns) > 2 else 0.0
    p95 = float(np.percentile(returns, 95)) if len(returns) > 1 else 0.0
    p5 = float(np.percentile(returns, 5)) if len(returns) > 1 else 1e-9
    tail_ratio = abs(p95 / p5) if abs(p5) > 1e-12 else 0.0

    monthly_heatmap: dict[str, dict[str, float]] = {}
    if dates and len(dates) == len(eq):
        try:
            dt_series = pd.to_datetime(dates, errors="coerce")
            monthly = pd.DataFrame({"date": dt_series, "equity": eq})
            monthly["year"] = monthly["date"].dt.strftime("%Y")
            monthly["month"] = monthly["date"].dt.strftime("%m")
            for (year, month), group in monthly.groupby(["year", "month"]):
                if len(group) > 1:
                    m_ret = (group["equity"].iloc[-1] / group["equity"].iloc[0] - 1) * 100
                    monthly_heatmap.setdefault(str(year), {})[str(month)] = round(m_ret, 2)
        except Exception as e:
            logger.debug("Monthly heatmap error: %s", e)

    n_bins = min(30, max(10, len(returns) // 10))
    hist, bin_edges = np.histogram(returns, bins=n_bins)
    return_hist = {
        "bins": [round(float(b), 6) for b in bin_edges],
        "counts": [int(c) for c in hist],
    }

    dist = DistributionAnalysis(
        skewness=round(skew, 4),
        kurtosis=round(kurt, 4),
        tail_ratio=round(tail_ratio, 4),
        monthly_return_heatmap=monthly_heatmap,
        return_histogram=return_hist,
    )

    warnings = _check_guardrails(n_trades, years, sharpe, total_return, max_dd, n_params)
    return ComprehensiveMetrics(
        returns=ret_metrics,
        risk=risk_metrics,
        risk_adjusted=risk_adj,
        trades=trade_stats,
        distribution=dist,
        guardrail_warnings=warnings,
    )


def _check_guardrails(n_trades: int, years: float, sharpe: float, total_return: float, max_dd: float, n_params: int) -> list[str]:
    warnings = []
    if n_trades < 15:
        warnings.append(f"CRITICAL: 交易次数仅{n_trades}次(<15)，无法得出统计结论")
    elif n_trades < 30:
        warnings.append(f"WARNING: 交易次数{n_trades}次(<30)，结论需谨慎")
    if years < 2.0:
        warnings.append(f"WARNING: 回测期间{years:.1f}年(<2年)，日频策略建议至少2年")
    if n_params * 100 > n_trades and n_trades > 0:
        warnings.append(f"WARNING: 参数数({n_params})×100 > 交易数({n_trades})，过拟合风险高")
    if sharpe > 3.0:
        warnings.append(f"WARNING: Sharpe={sharpe:.1f}>3.0，可能过拟合")
    if max_dd > 0.4:
        warnings.append(f"WARNING: 最大回撤{max_dd*100:.1f}%>40%，超出机构可接受范围")
    return warnings


class RuntimeRiskController:
    def __init__(
        self,
        initial_capital: float = 1_000_000,
        daily_loss_limit_pct: float = 0.03,
        max_open_positions: int = 5,
        max_portfolio_risk_pct: float = 0.15,
        max_correlated_positions: int = 3,
        maintenance_margin_pct: float = 0.25,
        leverage: float = 1.0,
    ):
        self._initial_capital = initial_capital
        self._daily_loss_limit_pct = daily_loss_limit_pct
        self._max_open_positions = max_open_positions
        self._max_portfolio_risk_pct = max_portfolio_risk_pct
        self._max_correlated_positions = max_correlated_positions
        self._maintenance_margin_pct = maintenance_margin_pct
        self._leverage = leverage
        self._daily_pnl: float = 0.0
        self._current_equity: float = initial_capital
        self._open_positions: list[dict] = []
        self._halted: bool = False

    def reset_daily(self) -> None:
        self._daily_pnl = 0.0
        self._halted = False

    def record_pnl(self, pnl: float, current_equity: float) -> None:
        self._daily_pnl += pnl
        self._current_equity = current_equity
        if self._daily_pnl < -self._daily_loss_limit_pct * current_equity:
            self._halted = True

    def can_open_position(self, position_risk_pct: float = 0.0, correlation: float = 0.0, same_sector_count: int = 0) -> tuple[bool, str]:
        if self._halted:
            return False, "日内亏损已达限制，暂停新开仓"
        if len(self._open_positions) >= self._max_open_positions:
            return False, f"持仓数已达上限({self._max_open_positions})"
        total_risk = sum(p.get("risk_pct", 0) for p in self._open_positions) + position_risk_pct
        if total_risk > self._max_portfolio_risk_pct:
            return False, f"组合风险敞口将超限({self._max_portfolio_risk_pct*100:.0f}%)"
        if correlation > 0.7 and same_sector_count >= self._max_correlated_positions:
            return False, f"相关性持仓数已达上限({self._max_correlated_positions})"
        return True, ""

    def scale_position_size(self, requested_size: float, position_risk_pct: float) -> float:
        total_existing_risk = sum(p.get("risk_pct", 0) for p in self._open_positions)
        remaining = self._max_portfolio_risk_pct - total_existing_risk
        if position_risk_pct <= remaining:
            return requested_size
        if remaining <= 0:
            return 0.0
        scale = remaining / max(position_risk_pct, 1e-9)
        return requested_size * scale

    def check_margin(self, position_value: float, cash: float) -> tuple[bool, float]:
        if self._leverage <= 1.0:
            return True, 0.0
        margin_ratio = cash / max(position_value / self._leverage, 1e-9)
        if margin_ratio < self._maintenance_margin_pct:
            return False, margin_ratio
        return True, margin_ratio

    def add_position(self, position: dict) -> None:
        self._open_positions.append(position)

    def remove_position(self, symbol: str) -> None:
        self._open_positions = [p for p in self._open_positions if p.get("symbol") != symbol]

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def open_position_count(self) -> int:
        return len(self._open_positions)
