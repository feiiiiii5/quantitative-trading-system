import logging
import math
from dataclasses import dataclass
from typing import Any

from quantcore_portfolio.account import Account, Position

logger = logging.getLogger(__name__)


@dataclass
class AttributionResult:
    alpha: float
    beta: float
    tracking_error: float
    information_ratio: float
    active_return: float


class PnLCalculator:
    def calculate_unrealized_pnl(self, position: Position, current_price: float) -> float:
        market_value = position.quantity * current_price
        cost_basis = position.quantity * position.avg_cost
        return market_value - cost_basis

    def calculate_daily_pnl(self, account: Account, prev_total_value: float) -> float:
        current_value = account.total_value
        if prev_total_value == 0:
            return 0.0
        return current_value - prev_total_value

    def calculate_twr(
        self, cash_flows: list[float], period_values: list[float]
    ) -> float:
        if len(period_values) < 2:
            return 0.0
        if len(cash_flows) != len(period_values) - 1:
            raise ValueError(
                "cash_flows length must be period_values length minus 1: "
                f"got {len(cash_flows)} flows, {len(period_values)} values"
            )

        twr = 1.0
        for i, (start_value, flow) in enumerate(zip(period_values[:-1], cash_flows)):
            end_value = period_values[i + 1]
            denominator = start_value + flow
            if denominator == 0:
                logger.warning("Zero denominator in TWR calculation at period %d", i)
                continue
            sub_period_return = (end_value - denominator) / denominator
            twr *= 1.0 + sub_period_return

        return twr - 1.0

    def calculate_mwr(
        self, cash_flows: list[float], period_values: list[float]
    ) -> float:
        if len(period_values) < 2:
            return 0.0
        if len(cash_flows) != len(period_values) - 1:
            raise ValueError(
                "cash_flows length must be period_values length minus 1: "
                f"got {len(cash_flows)} flows, {len(period_values)} values"
            )

        n = len(cash_flows)
        terminal_value = period_values[-1]

        def npv(rate: float) -> float:
            pv_flows = sum(
                cf / (1.0 + rate) ** (i + 1) for i, cf in enumerate(cash_flows)
            )
            pv_terminal = terminal_value / (1.0 + rate) ** n
            return pv_flows - pv_terminal + period_values[0]

        rate = self._newton_raphson(npv, initial_guess=0.1)
        if rate is None:
            logger.warning("MWR calculation did not converge, falling back to bisection")
            rate = self._bisection(npv)
        return rate if rate is not None else 0.0

    def calculate_attribution(
        self, pnl: float, benchmark_pnl: float, pnl_series: list[float] | None = None,
        benchmark_series: list[float] | None = None,
    ) -> AttributionResult:
        alpha = pnl - benchmark_pnl

        if pnl_series and benchmark_series and len(pnl_series) == len(benchmark_series):
            beta = self._calculate_beta(pnl_series, benchmark_series)
            diffs = [p - b for p, b in zip(pnl_series, benchmark_series)]
            tracking_error = (
                math.sqrt(sum(d ** 2 for d in diffs) / len(diffs))
                if diffs
                else 0.0
            )
        else:
            beta = 0.0
            tracking_error = abs(alpha)

        information_ratio = (
            alpha / tracking_error if tracking_error != 0 else 0.0
        )

        return AttributionResult(
            alpha=alpha,
            beta=beta,
            tracking_error=tracking_error,
            information_ratio=information_ratio,
            active_return=alpha,
        )

    @staticmethod
    def _calculate_beta(
        portfolio_returns: list[float], benchmark_returns: list[float]
    ) -> float:
        n = len(portfolio_returns)
        if n < 2:
            return 0.0
        mean_p = sum(portfolio_returns) / n
        mean_b = sum(benchmark_returns) / n
        covariance = sum(
            (p - mean_p) * (b - mean_b)
            for p, b in zip(portfolio_returns, benchmark_returns)
        ) / (n - 1)
        variance = sum((b - mean_b) ** 2 for b in benchmark_returns) / (n - 1)
        return covariance / variance if variance != 0 else 0.0

    @staticmethod
    def _newton_raphson(
        f: Any, initial_guess: float = 0.1, tol: float = 1e-8, max_iter: int = 1000
    ) -> float | None:
        rate = initial_guess
        h = 1e-7
        for _ in range(max_iter):
            f_val = f(rate)
            if abs(f_val) < tol:
                return rate
            f_prime = (f(rate + h) - f(rate - h)) / (2.0 * h)
            if f_prime == 0:
                return None
            rate -= f_val / f_prime
            if abs(rate) > 1e6:
                return None
        return None

    @staticmethod
    def _bisection(
        f: Any, lo: float = -0.99, hi: float = 10.0, tol: float = 1e-8, max_iter: int = 1000
    ) -> float | None:
        f_lo = f(lo)
        f_hi = f(hi)
        if f_lo * f_hi > 0:
            return None
        for _ in range(max_iter):
            mid = (lo + hi) / 2.0
            f_mid = f(mid)
            if abs(f_mid) < tol or (hi - lo) / 2.0 < tol:
                return mid
            if f_lo * f_mid < 0:
                hi = mid
            else:
                lo = mid
                f_lo = f_mid
        return (lo + hi) / 2.0
