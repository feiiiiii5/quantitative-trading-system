import logging
import time
from concurrent import futures
from datetime import date, datetime
from typing import Optional

import grpc

from generated import portfolio_pb2, portfolio_pb2_grpc
from quantcore_portfolio.account import AccountManager, FillResult
from quantcore_portfolio.pnl import PnLCalculator

logger = logging.getLogger(__name__)

_ACCOUNT_NOT_FOUND = "Account {account_id} not found"


class PortfolioServiceServicer(portfolio_pb2_grpc.PortfolioServiceServicer):
    def __init__(
        self,
        account_manager: AccountManager,
        pnl_calculator: PnLCalculator,
    ) -> None:
        self._account_manager = account_manager
        self._pnl_calculator = pnl_calculator
        self._prev_total_values: dict[str, float] = {}
        self._commission_history: dict[str, list[tuple[date, float]]] = {}

    def GetPortfolio(self, request: portfolio_pb2.PortfolioRequest, context: grpc.ServicerContext) -> portfolio_pb2.PortfolioResponse:
        account_id = request.account_id
        account = self._account_manager.get_account(account_id)
        if account is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(_ACCOUNT_NOT_FOUND.format(account_id=account_id))
            return portfolio_pb2.PortfolioResponse()

        total_value = account.total_value
        market_value = account.total_market_value
        unrealized_pnl = account.total_unrealized_pnl

        prev_value = self._prev_total_values.get(account_id, total_value)
        daily_return_pct = (
            (total_value - prev_value) / prev_value * 100 if prev_value != 0 else 0.0
        )

        initial_cash = account.cash + market_value - unrealized_pnl
        total_return_pct = (
            (total_value - initial_cash) / initial_cash * 100 if initial_cash != 0 else 0.0
        )

        realized_pnl = self._account_manager.get_realized_pnl(
            account_id, date.min, date.max
        )

        return portfolio_pb2.PortfolioResponse(
            account_id=account_id,
            total_value=total_value,
            cash=account.cash,
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            total_return_pct=total_return_pct,
            daily_return_pct=daily_return_pct,
            timestamp_ns=time.time_ns(),
        )

    def GetPositions(self, request: portfolio_pb2.PositionsRequest, context: grpc.ServicerContext) -> portfolio_pb2.PositionsResponse:
        account_id = request.account_id
        account = self._account_manager.get_account(account_id)
        if account is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(_ACCOUNT_NOT_FOUND.format(account_id=account_id))
            return portfolio_pb2.PositionsResponse()

        symbols = list(request.symbols) if request.symbols else list(account.positions.keys())
        proto_positions = []
        for symbol in symbols:
            pos = account.positions.get(symbol)
            if pos is None:
                continue
            proto_positions.append(portfolio_pb2.Position(
                symbol=pos.symbol,
                quantity=pos.quantity,
                avg_cost=pos.avg_cost,
                current_price=pos.current_price,
                market_value=pos.market_value,
                unrealized_pnl=pos.unrealized_pnl,
                unrealized_pnl_pct=pos.unrealized_pnl_pct,
                weight_pct=pos.weight_pct,
                timestamp_ns=pos.timestamp_ns,
            ))

        return portfolio_pb2.PositionsResponse(positions=proto_positions)

    def GetPnL(self, request: portfolio_pb2.PnLRequest, context: grpc.ServicerContext) -> portfolio_pb2.PnLResponse:
        account_id = request.account_id
        account = self._account_manager.get_account(account_id)
        if account is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(_ACCOUNT_NOT_FOUND.format(account_id=account_id))
            return portfolio_pb2.PnLResponse()

        try:
            start_date = date.fromisoformat(request.start_date)
            end_date = date.fromisoformat(request.end_date)
        except ValueError as e:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(f"Invalid date format: {e}")
            return portfolio_pb2.PnLResponse()

        realized_pnl = self._account_manager.get_realized_pnl(account_id, start_date, end_date)
        unrealized_pnl = account.total_unrealized_pnl
        total_pnl = realized_pnl + unrealized_pnl

        commission_cost = sum(
            amt
            for d, amt in self._commission_history.get(account_id, [])
            if start_date <= d <= end_date
        )

        daily_breakdown = self._build_daily_breakdown(
            account_id, start_date, end_date, realized_pnl
        )

        return portfolio_pb2.PnLResponse(
            total_pnl=total_pnl,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            commission_cost=commission_cost,
            slippage_cost=0.0,
            daily_breakdown=daily_breakdown,
        )

    def StreamPortfolioUpdates(
        self, request: portfolio_pb2.PortfolioStreamRequest, context: grpc.ServicerContext
    ) -> None:
        account_id = request.account_id
        interval_ms = max(request.interval_ms, 100)

        logger.info(
            "Stream started: account=%s interval_ms=%d", account_id, interval_ms
        )

        prev_total_value: Optional[float] = None

        while context.is_active():
            account = self._account_manager.get_account(account_id)
            if account is None:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(_ACCOUNT_NOT_FOUND.format(account_id=account_id))
                return

            total_value = account.total_value
            unrealized_pnl = account.total_unrealized_pnl

            if prev_total_value is not None and prev_total_value != 0:
                daily_return_pct = (total_value - prev_total_value) / prev_total_value * 100
            else:
                daily_return_pct = 0.0

            prev_total_value = total_value

            event_type = "heartbeat"
            if account.positions:
                event_type = "position_update"

            update = portfolio_pb2.PortfolioUpdate(
                account_id=account_id,
                total_value=total_value,
                unrealized_pnl=unrealized_pnl,
                daily_return_pct=daily_return_pct,
                timestamp_ns=time.time_ns(),
                event_type=event_type,
            )

            yield update

            time.sleep(interval_ms / 1000.0)

        logger.info("Stream ended: account=%s", account_id)

    def record_commission(self, account_id: str, commission: float) -> None:
        if account_id not in self._commission_history:
            self._commission_history[account_id] = []
        self._commission_history[account_id].append((date.today(), commission))

    _MAX_DAILY_BREAKDOWN_DAYS = 366

    def _build_daily_breakdown(
        self,
        account_id: str,
        start_date: date,
        end_date: date,
        total_realized: float,
    ) -> list[portfolio_pb2.DailyPnL]:
        account = self._account_manager.get_account(account_id)
        if account is None:
            return []

        daily: list[portfolio_pb2.DailyPnL] = []
        cumulative = 0.0
        peak = 0.0
        num_days = max((end_date - start_date).days, 1)
        daily_realized = total_realized / num_days if num_days > 0 else 0.0

        capped_end = min(
            end_date,
            start_date + __import__("datetime").timedelta(days=self._MAX_DAILY_BREAKDOWN_DAYS - 1),
        )
        current = start_date
        while current <= capped_end:
            cumulative += daily_realized
            peak = max(peak, cumulative)
            drawdown = cumulative - peak

            daily.append(portfolio_pb2.DailyPnL(
                date=current.isoformat(),
                pnl=round(daily_realized, 4),
                cumulative_pnl=round(cumulative, 4),
                drawdown=round(drawdown, 4),
            ))
            current += __import__("datetime").timedelta(days=1)

        return daily


def create_server(
    account_manager: AccountManager,
    pnl_calculator: PnLCalculator,
    port: int = 50055,
    max_workers: int = 10,
) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    servicer = PortfolioServiceServicer(account_manager, pnl_calculator)
    portfolio_pb2_grpc.add_PortfolioServiceServicer_to_server(servicer, server)
    server.add_insecure_port(f"[::]:{port}")
    logger.info("Portfolio gRPC server configured on port %d with %d workers", port, max_workers)
    return server
