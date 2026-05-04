import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskMetrics:
    volatility: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    beta: float = 0.0
    exposure: float = 0.0
    concentration: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW
    warnings: List[str] = field(default_factory=list)


@dataclass
class PositionLimit:
    max_single_position: float = 0.10
    max_sector_position: float = 0.30
    max_total_exposure: float = 1.0
    max_leverage: float = 1.0


class EnhancedRiskMonitor:
    def __init__(
        self,
        position_limit: PositionLimit = None,
        max_drawdown_threshold: float = 0.15,
        volatility_threshold: float = 0.30,
        var_threshold: float = 0.05,
        lookback_window: int = 60,
    ):
        self._position_limit = position_limit or PositionLimit()
        self._max_dd_threshold = max_drawdown_threshold
        self._vol_threshold = volatility_threshold
        self._var_threshold = var_threshold
        self._lookback = lookback_window
        self._equity_curve: List[float] = []
        self._position_history: List[Dict] = []
        self._history_max = 252

    def update_equity(self, equity: float) -> None:
        self._equity_curve.append(equity)
        if len(self._equity_curve) > self._history_max:
            self._equity_curve = self._equity_curve[-self._history_max:]

    def update_positions(self, positions: Dict[str, float]) -> None:
        self._position_history.append(positions)
        if len(self._position_history) > self._history_max:
            self._position_history = self._position_history[-self._history_max:]

    def calc_volatility(self, returns: pd.Series = None) -> float:
        if returns is not None and len(returns) > 1:
            return float(returns.iloc[-self._lookback:].std() * np.sqrt(252))
        if len(self._equity_curve) < 2:
            return 0.0
        eq = pd.Series(self._equity_curve)
        rets = eq.pct_change().dropna()
        if len(rets) < 2:
            return 0.0
        return float(rets.iloc[-self._lookback:].std() * np.sqrt(252))

    def calc_max_drawdown(self) -> float:
        if len(self._equity_curve) < 2:
            return 0.0
        eq = pd.Series(self._equity_curve)
        cummax = eq.cummax()
        drawdown = (eq - cummax) / cummax
        return float(drawdown.min())

    def calc_current_drawdown(self) -> float:
        if len(self._equity_curve) < 2:
            return 0.0
        eq = pd.Series(self._equity_curve)
        peak = eq.cummax().iloc[-1]
        current = eq.iloc[-1]
        return float((current - peak) / peak)

    def calc_var(self, returns: pd.Series = None, confidence: float = 0.95) -> float:
        if returns is not None:
            r = returns.iloc[-self._lookback:]
        elif len(self._equity_curve) >= 2:
            eq = pd.Series(self._equity_curve)
            r = eq.pct_change().dropna().iloc[-self._lookback:]
        else:
            return 0.0
        if len(r) < 5:
            return 0.0
        return float(np.percentile(r, (1 - confidence) * 100))

    def calc_cvar(self, returns: pd.Series = None, confidence: float = 0.95) -> float:
        if returns is not None:
            r = returns.iloc[-self._lookback:]
        elif len(self._equity_curve) >= 2:
            eq = pd.Series(self._equity_curve)
            r = eq.pct_change().dropna().iloc[-self._lookback:]
        else:
            return 0.0
        if len(r) < 5:
            return 0.0
        threshold = np.percentile(r, (1 - confidence) * 100)
        tail = r[r <= threshold]
        return float(tail.mean()) if len(tail) > 0 else float(threshold)

    def calc_sharpe(self, returns: pd.Series = None, risk_free: float = 0.03) -> float:
        if returns is not None:
            r = returns.iloc[-self._lookback:]
        elif len(self._equity_curve) >= 2:
            eq = pd.Series(self._equity_curve)
            r = eq.pct_change().dropna().iloc[-self._lookback:]
        else:
            return 0.0
        if len(r) < 2:
            return 0.0
        excess = r - risk_free / 252
        std = excess.std()
        if std < 1e-12:
            return 0.0
        return float(excess.mean() / std * np.sqrt(252))

    def calc_sortino(self, returns: pd.Series = None, risk_free: float = 0.03) -> float:
        if returns is not None:
            r = returns.iloc[-self._lookback:]
        elif len(self._equity_curve) >= 2:
            eq = pd.Series(self._equity_curve)
            r = eq.pct_change().dropna().iloc[-self._lookback:]
        else:
            return 0.0
        if len(r) < 2:
            return 0.0
        excess = r - risk_free / 252
        downside = excess[excess < 0]
        downside_std = np.sqrt(np.mean(downside ** 2)) if len(downside) > 0 else 0.0
        if downside_std < 1e-12:
            return 0.0
        return float(excess.mean() / downside_std * np.sqrt(252))

    def calc_beta(self, returns: pd.Series, benchmark_returns: pd.Series) -> float:
        if len(returns) < 2 or len(benchmark_returns) < 2:
            return 0.0
        n = min(len(returns), len(benchmark_returns))
        r = returns.iloc[-n:].values
        b = benchmark_returns.iloc[-n:].values
        cov = np.cov(r, b)
        if cov[1, 1] < 1e-12:
            return 0.0
        return float(cov[0, 1] / cov[1, 1])

    def calc_exposure(self, positions: Dict[str, float], total_equity: float) -> float:
        if total_equity <= 0:
            return 0.0
        total_position_value = sum(abs(v) for v in positions.values())
        return total_position_value / total_equity

    def calc_concentration(self, positions: Dict[str, float]) -> float:
        if not positions:
            return 0.0
        total = sum(abs(v) for v in positions.values())
        if total < 1e-12:
            return 0.0
        weights = np.array([abs(v) / total for v in positions.values()])
        return float(np.sum(weights ** 2))

    def check_position_limits(
        self,
        positions: Dict[str, float],
        total_equity: float,
        sector_map: Dict[str, str] = None,
    ) -> List[str]:
        violations = []
        if total_equity <= 0:
            return violations

        for symbol, value in positions.items():
            weight = abs(value) / total_equity
            if weight > self._position_limit.max_single_position:
                violations.append(
                    f"单标的仓位超限: {symbol} = {weight:.2%} > {self._position_limit.max_single_position:.2%}"
                )

        if sector_map:
            sector_exposure = {}
            for symbol, value in positions.items():
                sector = sector_map.get(symbol, "unknown")
                sector_exposure[sector] = sector_exposure.get(sector, 0) + abs(value)
            for sector, value in sector_exposure.items():
                weight = value / total_equity
                if weight > self._position_limit.max_sector_position:
                    violations.append(
                        f"行业仓位超限: {sector} = {weight:.2%} > {self._position_limit.max_sector_position:.2%}"
                    )

        total_exposure = self.calc_exposure(positions, total_equity)
        if total_exposure > self._position_limit.max_total_exposure:
            violations.append(
                f"总敞口超限: {total_exposure:.2%} > {self._position_limit.max_total_exposure:.2%}"
            )

        return violations

    def get_risk_metrics(
        self,
        positions: Dict[str, float] = None,
        total_equity: float = 0,
        returns: pd.Series = None,
        benchmark_returns: pd.Series = None,
        sector_map: Dict[str, str] = None,
    ) -> RiskMetrics:
        warnings = []

        vol = self.calc_volatility(returns)
        max_dd = self.calc_max_drawdown()
        cur_dd = self.calc_current_drawdown()
        var_95 = self.calc_var(returns, 0.95)
        cvar_95 = self.calc_cvar(returns, 0.95)
        sharpe = self.calc_sharpe(returns)
        sortino = self.calc_sortino(returns)
        beta = self.calc_beta(returns, benchmark_returns) if benchmark_returns is not None else 0.0
        exposure = self.calc_exposure(positions, total_equity) if positions else 0.0
        concentration = self.calc_concentration(positions) if positions else 0.0

        if vol > self._vol_threshold:
            warnings.append(f"波动率过高: {vol:.2%} > {self._vol_threshold:.2%}")
        if abs(max_dd) > self._max_dd_threshold:
            warnings.append(f"最大回撤超限: {max_dd:.2%} < -{self._max_dd_threshold:.2%}")
        if abs(var_95) > self._var_threshold:
            warnings.append(f"VaR超限: {var_95:.4f}")

        if positions and total_equity > 0:
            pos_violations = self.check_position_limits(positions, total_equity, sector_map)
            warnings.extend(pos_violations)

        if abs(cur_dd) > 0.20:
            risk_level = RiskLevel.CRITICAL
        elif abs(cur_dd) > 0.10 or vol > self._vol_threshold:
            risk_level = RiskLevel.HIGH
        elif abs(cur_dd) > 0.05 or vol > self._vol_threshold * 0.7:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW

        return RiskMetrics(
            volatility=round(vol, 6),
            max_drawdown=round(max_dd, 6),
            current_drawdown=round(cur_dd, 6),
            var_95=round(var_95, 6),
            cvar_95=round(cvar_95, 6),
            sharpe_ratio=round(sharpe, 4),
            sortino_ratio=round(sortino, 4),
            beta=round(beta, 4),
            exposure=round(exposure, 6),
            concentration=round(concentration, 6),
            risk_level=risk_level,
            warnings=warnings,
        )

    def should_force_liquidate(self, metrics: RiskMetrics) -> Tuple[bool, str]:
        if metrics.risk_level == RiskLevel.CRITICAL:
            return True, "风险等级为CRITICAL，强制清仓"
        if abs(metrics.current_drawdown) > 0.25:
            return True, f"当前回撤 {metrics.current_drawdown:.2%} 超过25%强制清仓线"
        if abs(metrics.var_95) > 0.10:
            return True, f"VaR(95%) = {metrics.var_95:.4f} 超过10%强制清仓线"
        return False, ""

    def should_reduce_position(self, metrics: RiskMetrics) -> Tuple[bool, float, str]:
        if metrics.risk_level == RiskLevel.HIGH:
            return True, 0.5, "风险等级为HIGH，建议减仓50%"
        if abs(metrics.current_drawdown) > 0.15:
            return True, 0.5, f"当前回撤 {metrics.current_drawdown:.2%} 超过15%，建议减仓50%"
        if metrics.volatility > self._vol_threshold:
            return True, 0.7, f"波动率 {metrics.volatility:.2%} 过高，建议减仓至70%"
        return False, 1.0, ""


def calc_position_size(
    capital: float,
    price: float,
    volatility: float,
    target_vol: float = 0.15,
    max_position_pct: float = 0.10,
) -> int:
    if price <= 0 or volatility <= 1e-10:
        return 0
    vol_adjusted_size = (target_vol / volatility) * capital * max_position_pct
    shares = int(vol_adjusted_size / price)
    max_shares = int(capital * max_position_pct / price)
    return min(shares, max_shares)
