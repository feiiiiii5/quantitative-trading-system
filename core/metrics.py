import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

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


def calc_cagr(equity_curve: list[float], n_days: int | None = None) -> float:
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
    downside_std = np.sqrt(np.mean(downside ** 2)) if len(downside) > 0 else excess.std()
    if downside_std < 1e-12:
        return 0.0
    return float(excess.mean() / downside_std * np.sqrt(252))


def calc_max_drawdown(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0
    eq = pd.Series(equity_curve)
    if not np.all(np.isfinite(eq)):
        eq = eq.ffill().bfill()
    cummax = eq.cummax()
    drawdown = (eq - cummax) / cummax.replace(0, np.nan)
    result = float(drawdown.min())
    return result if np.isfinite(result) else 0.0


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
        return 99.0 if len(wins) > 0 else 0.0
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses.mean())
    if avg_loss < 1e-12:
        return 99.0
    return float(avg_win / avg_loss)


def calc_turnover(positions_history: list[dict[str, float]], total_equity: float | None = None) -> float:
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
        return total_turnover / (2 * total_equity * (len(positions_history) - 1))
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


def calc_alpha_beta(returns: pd.Series, benchmark_returns: pd.Series, risk_free: float = 0.03) -> tuple:
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


def _finite(value: float, fallback: float = 0.0) -> float:
    if not np.isfinite(value):
        return fallback
    return value


def calc_all_metrics(
    equity_curve: list[float],
    returns: pd.Series | None = None,
    benchmark_returns: pd.Series | None = None,
    positions_history: list[dict[str, float]] | None = None,
    risk_free: float = 0.03,
) -> InstitutionalMetrics:
    if len(equity_curve) < 2:
        return InstitutionalMetrics()

    eq = pd.Series(equity_curve)
    if not np.all(np.isfinite(eq)):
        eq = eq.replace([np.inf, -np.inf], np.nan).ffill().bfill()
    if returns is None:
        returns = eq.pct_change().dropna()
    if len(returns) < 1:
        return InstitutionalMetrics()

    cagr = calc_cagr(equity_curve)
    sharpe = calc_sharpe(returns, risk_free)
    sortino = calc_sortino(returns, risk_free)
    max_dd = calc_max_drawdown(equity_curve)
    calmar = calc_calmar(cagr, max_dd)
    vol = _finite(float(returns.std() * np.sqrt(252)))
    win_rate = calc_win_rate(returns)
    pl_ratio = calc_profit_loss_ratio(returns)
    total_return = _finite(float(eq.iloc[-1] / eq.iloc[0] - 1)) if eq.iloc[0] > 0 else 0.0
    turnover = calc_turnover(positions_history) if positions_history else 0.0
    var_95 = calc_var(returns)
    cvar_95 = calc_cvar(returns)
    skewness = _finite(float(returns.skew())) if len(returns) > 2 else 0.0
    kurtosis = _finite(float(returns.kurtosis())) if len(returns) > 2 else 0.0
    max_consec_wins = calc_max_consecutive(returns, True)
    max_consec_losses = calc_max_consecutive(returns, False)

    alpha_val = 0.0
    beta_val = 0.0
    ir = 0.0
    te = 0.0
    if benchmark_returns is not None and len(benchmark_returns) >= 2:
        alpha_val, beta_val = calc_alpha_beta(returns, benchmark_returns, risk_free)
        ir = calc_information_ratio(returns, benchmark_returns)
        n = min(len(returns), len(benchmark_returns))
        active = returns.iloc[-n:] - benchmark_returns.iloc[-n:]
        te = _finite(float(active.std() * np.sqrt(252)))

    return InstitutionalMetrics(
        cagr=round(_finite(cagr), 6),
        sharpe_ratio=round(_finite(sharpe), 4),
        sortino_ratio=round(_finite(sortino), 4),
        max_drawdown=round(_finite(max_dd), 6),
        calmar_ratio=round(_finite(calmar), 4),
        volatility=round(_finite(vol), 6),
        win_rate=round(_finite(win_rate), 4),
        profit_loss_ratio=round(_finite(pl_ratio, 99.0), 4),
        total_return=round(_finite(total_return), 6),
        annual_turnover=round(_finite(turnover), 6),
        var_95=round(_finite(var_95), 6),
        cvar_95=round(_finite(cvar_95), 6),
        information_ratio=round(_finite(ir), 4),
        tracking_error=round(_finite(te), 6),
        alpha=round(_finite(alpha_val), 6),
        beta=round(_finite(beta_val), 4),
        skewness=round(_finite(skewness), 4),
        kurtosis=round(_finite(kurtosis), 4),
        n_trades=len(returns),
        max_consecutive_wins=max_consec_wins,
        max_consecutive_losses=max_consec_losses,
    )


def metrics_to_dict(metrics: InstitutionalMetrics) -> dict:
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


@dataclass
class RollingRiskSnapshot:
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    volatility: float = 0.0
    max_drawdown: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    win_rate: float = 0.0


class RollingRiskTracker:
    """Incrementally computes rolling risk metrics with O(1) per-bar update cost.

    Maintains a fixed-size deque of returns and equity values, enabling
    real-time risk monitoring without recomputing from scratch each bar.
    """

    def __init__(
        self,
        window: int = 60,
        risk_free: float = 0.03,
        max_equity_history: int = 252,
    ):
        from collections import deque
        self._window = window
        self._risk_free = risk_free
        self._returns: deque = deque(maxlen=window)
        self._equity: deque = deque(maxlen=max_equity_history)
        self._peak_equity: float = 0.0
        self._max_dd: float = 0.0
        self._wins: int = 0
        self._total: int = 0

    def update(self, equity: float) -> RollingRiskSnapshot:
        prev_equity = self._equity[-1] if self._equity else equity
        self._equity.append(equity)

        ret = (equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
        if not np.isfinite(ret):
            ret = 0.0
        self._returns.append(ret)

        self._total += 1
        if ret > 0:
            self._wins += 1

        if equity > self._peak_equity:
            self._peak_equity = equity
        if self._peak_equity > 0:
            dd = (equity - self._peak_equity) / self._peak_equity
            if dd < self._max_dd:
                self._max_dd = dd

        return self.snapshot()

    def snapshot(self) -> RollingRiskSnapshot:
        if len(self._returns) < 2:
            return RollingRiskSnapshot()

        rets = np.array(self._returns)
        if not np.all(np.isfinite(rets)):
            rets = np.nan_to_num(rets, nan=0.0, posinf=0.0, neginf=0.0)

        excess = rets - self._risk_free / 252
        std = float(np.std(excess))
        sharpe = float(np.mean(excess) / std * np.sqrt(252)) if std > 1e-12 else 0.0

        downside = excess[excess < 0]
        downside_std = float(np.sqrt(np.mean(downside ** 2))) if len(downside) > 0 else 0.0
        sortino = float(np.mean(excess) / downside_std * np.sqrt(252)) if downside_std > 1e-12 else 0.0

        vol = float(np.std(rets) * np.sqrt(252))

        calmar = 0.0
        if abs(self._max_dd) > 1e-12:
            annualized_ret = float(np.mean(rets) * 252)
            calmar = annualized_ret / abs(self._max_dd)

        var_95 = 0.0
        cvar_95 = 0.0
        if len(rets) >= 10:
            var_95 = float(np.percentile(rets, 5))
            tail = rets[rets <= var_95]
            cvar_95 = float(np.mean(tail)) if len(tail) > 0 else var_95

        win_rate = self._wins / max(self._total, 1)

        return RollingRiskSnapshot(
            sharpe=round(_finite(sharpe), 4),
            sortino=round(_finite(sortino), 4),
            calmar=round(_finite(calmar), 4),
            volatility=round(_finite(vol), 6),
            max_drawdown=round(_finite(self._max_dd), 6),
            var_95=round(_finite(var_95), 6),
            cvar_95=round(_finite(cvar_95), 6),
            win_rate=round(_finite(win_rate), 4),
        )

    def reset(self) -> None:
        self._returns.clear()
        self._equity.clear()
        self._peak_equity = 0.0
        self._max_dd = 0.0
        self._wins = 0
        self._total = 0


@dataclass
class DrawdownEpisode:
    start_idx: int = 0
    trough_idx: int = 0
    end_idx: int = 0
    depth: float = 0.0
    duration_bars: int = 0
    recovery_bars: int = 0
    recovered: bool = False


def analyze_drawdowns(equity_curve: list[float], top_n: int = 5) -> dict:
    """Analyze drawdown episodes: depth, duration, recovery time.

    Returns the top N worst drawdowns with full episode information
    including how long each took to recover.
    """
    if len(equity_curve) < 2:
        return {"episodes": [], "avg_recovery_bars": 0, "recovery_rate": 0.0}

    eq = np.array(equity_curve, dtype=float)
    if not np.all(np.isfinite(eq)):
        eq = np.nan_to_num(eq, nan=0.0, posinf=0.0, neginf=0.0)

    cummax = np.maximum.accumulate(eq)
    drawdown = np.where(cummax > 0, (eq - cummax) / cummax, 0.0)

    episodes = []
    in_drawdown = False
    start_idx = 0
    trough_idx = 0
    trough_val = 0.0

    for i in range(len(drawdown)):
        if drawdown[i] < 0 and not in_drawdown:
            in_drawdown = True
            start_idx = i
            trough_idx = i
            trough_val = drawdown[i]
        elif drawdown[i] < 0 and in_drawdown:
            if drawdown[i] < trough_val:
                trough_idx = i
                trough_val = drawdown[i]
        elif drawdown[i] >= 0 and in_drawdown:
            depth = trough_val
            duration = trough_idx - start_idx
            recovery = i - trough_idx
            episodes.append(DrawdownEpisode(
                start_idx=int(start_idx),
                trough_idx=int(trough_idx),
                end_idx=int(i),
                depth=round(float(depth), 6),
                duration_bars=int(duration),
                recovery_bars=int(recovery),
                recovered=True,
            ))
            in_drawdown = False

    if in_drawdown:
        depth = trough_val
        duration = trough_idx - start_idx
        recovery = len(drawdown) - trough_idx
        episodes.append(DrawdownEpisode(
            start_idx=int(start_idx),
            trough_idx=int(trough_idx),
            end_idx=len(drawdown) - 1,
            depth=round(float(depth), 6),
            duration_bars=int(duration),
            recovery_bars=int(recovery),
            recovered=False,
        ))

    episodes.sort(key=lambda e: e.depth)
    top_episodes = episodes[:top_n]

    recovered_count = sum(1 for e in top_episodes if e.recovered)
    avg_recovery = 0.0
    recovered_episodes = [e for e in top_episodes if e.recovered]
    if recovered_episodes:
        avg_recovery = float(np.mean([e.recovery_bars for e in recovered_episodes]))

    return {
        "episodes": [
            {
                "start_idx": e.start_idx,
                "trough_idx": e.trough_idx,
                "end_idx": e.end_idx,
                "depth": e.depth,
                "duration_bars": e.duration_bars,
                "recovery_bars": e.recovery_bars,
                "recovered": e.recovered,
            }
            for e in top_episodes
        ],
        "avg_recovery_bars": round(avg_recovery, 1),
        "recovery_rate": round(recovered_count / max(len(top_episodes), 1), 4),
        "total_episodes": len(episodes),
    }





class MetricsCollector:
    """轻量级系统指标收集器，用于监控API延迟、数据源请求、回测耗时等"""

    def __init__(self):
        self._counters: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._lock = threading.Lock()

    def increment(self, name: str, value: int = 1, tags: dict | None = None) -> None:
        with self._lock:
            key = self._make_key(name, tags)
            self._counters[key] += value

    def gauge(self, name: str, value: float, tags: dict | None = None) -> None:
        with self._lock:
            key = self._make_key(name, tags)
            self._gauges[key] = value

    def histogram(self, name: str, value: float, tags: dict | None = None) -> None:
        with self._lock:
            key = self._make_key(name, tags)
            self._histograms[key].append(value)

    def timer(self, name: str, value: float | None = None, tags: dict | None = None):
        if value is not None:
            self.histogram(name, value, tags)
            return None
        return _TimerContext(self, name, tags)

    def get_summary(self) -> dict:
        with self._lock:
            result: dict[str, object] = {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {},
            }
            for k, v in self._histograms.items():
                if v:
                    arr = sorted(v)
                    n = len(arr)
                    result["histograms"][k] = {
                        "count": n,
                        "mean": round(sum(arr) / n, 4),
                        "p50": round(arr[n // 2], 4),
                        "p95": round(arr[int(n * 0.95)], 4),
                        "p99": round(arr[int(n * 0.99)], 4),
                    }
            return result

    def _make_key(self, name: str, tags: dict | None = None) -> str:
        if not tags:
            return name
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name}{{{tag_str}}}"


class _TimerContext:
    def __init__(self, collector: MetricsCollector, name: str, tags: dict | None = None):
        self._collector = collector
        self._name = name
        self._tags = tags
        self._start = 0.0

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, *args):
        elapsed = time.monotonic() - self._start
        self._collector.histogram(self._name, elapsed, self._tags)

    async def __aenter__(self):
        self._start = time.monotonic()
        return self

    async def __aexit__(self, *args):
        elapsed = time.monotonic() - self._start
        self._collector.histogram(self._name, elapsed, self._tags)


metrics = MetricsCollector()


def get_metrics() -> MetricsCollector:
    return metrics
