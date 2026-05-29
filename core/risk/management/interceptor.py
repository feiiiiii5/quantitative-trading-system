from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class InterceptorAction(Enum):
    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"


@dataclass(slots=True)
class OrderContext:
    symbol: str
    side: str
    quantity: float
    price: float
    portfolio_value: float = 0.0
    current_positions: dict[str, float] = field(default_factory=dict)
    daily_pnl: float = 0.0
    max_daily_loss_pct: float = 0.02
    max_position_pct: float = 0.20
    max_open_trades: int = 10
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class InterceptorResult:
    action: InterceptorAction
    interceptor_name: str
    reason: str = ""
    modified_quantity: float | None = None
    modified_price: float | None = None


class RiskInterceptor:
    def check(self, ctx: OrderContext) -> InterceptorResult:
        raise NotImplementedError


class DailyLossInterceptor(RiskInterceptor):
    def check(self, ctx: OrderContext) -> InterceptorResult:
        if ctx.portfolio_value <= 0:
            return InterceptorResult(action=InterceptorAction.APPROVE, interceptor_name="daily_loss")
        loss_pct = abs(ctx.daily_pnl) / ctx.portfolio_value if ctx.daily_pnl < 0 else 0
        if loss_pct > ctx.max_daily_loss_pct:
            return InterceptorResult(
                action=InterceptorAction.REJECT,
                interceptor_name="daily_loss",
                reason=f"Daily loss {loss_pct:.2%} exceeds limit {ctx.max_daily_loss_pct:.2%}",
            )
        return InterceptorResult(action=InterceptorAction.APPROVE, interceptor_name="daily_loss")


class ConcentrationInterceptor(RiskInterceptor):
    def check(self, ctx: OrderContext) -> InterceptorResult:
        if ctx.portfolio_value <= 0:
            return InterceptorResult(action=InterceptorAction.APPROVE, interceptor_name="concentration")
        order_value = ctx.quantity * ctx.price
        order_value / ctx.portfolio_value
        existing_value = ctx.current_positions.get(ctx.symbol, 0.0)
        total_pct = (existing_value + order_value) / ctx.portfolio_value
        if total_pct > ctx.max_position_pct:
            max_qty = (ctx.max_position_pct * ctx.portfolio_value - existing_value) / ctx.price if ctx.price > 0 else 0
            if max_qty > 0:
                return InterceptorResult(
                    action=InterceptorAction.MODIFY,
                    interceptor_name="concentration",
                    reason=f"Position {total_pct:.2%} would exceed {ctx.max_position_pct:.2%}",
                    modified_quantity=max_qty,
                )
            return InterceptorResult(
                action=InterceptorAction.REJECT,
                interceptor_name="concentration",
                reason=f"Position already at {existing_value / ctx.portfolio_value:.2%}",
            )
        return InterceptorResult(action=InterceptorAction.APPROVE, interceptor_name="concentration")


class MaxTradesInterceptor(RiskInterceptor):
    def check(self, ctx: OrderContext) -> InterceptorResult:
        open_count = len(ctx.current_positions)
        if open_count >= ctx.max_open_trades:
            return InterceptorResult(
                action=InterceptorAction.REJECT,
                interceptor_name="max_trades",
                reason=f"Open trades {open_count} >= limit {ctx.max_open_trades}",
            )
        return InterceptorResult(action=InterceptorAction.APPROVE, interceptor_name="max_trades")


class InterceptorChain:
    def __init__(self, interceptors: list[RiskInterceptor] | None = None) -> None:
        self._interceptors: list[RiskInterceptor] = interceptors or [
            DailyLossInterceptor(),
            ConcentrationInterceptor(),
            MaxTradesInterceptor(),
        ]

    def evaluate(self, ctx: OrderContext) -> InterceptorResult:
        for interceptor in self._interceptors:
            result = interceptor.check(ctx)
            if result.action == InterceptorAction.REJECT:
                logger.warning("Order REJECTED by %s: %s", result.interceptor_name, result.reason)
                return result
            if result.action == InterceptorAction.MODIFY:
                if result.modified_quantity is not None:
                    ctx.quantity = result.modified_quantity
                if result.modified_price is not None:
                    ctx.price = result.modified_price
                logger.info("Order MODIFIED by %s: %s", result.interceptor_name, result.reason)
        return InterceptorResult(action=InterceptorAction.APPROVE, interceptor_name="chain")

    def add_interceptor(self, interceptor: RiskInterceptor) -> None:
        self._interceptors.append(interceptor)
