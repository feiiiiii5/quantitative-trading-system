import asyncio
import logging
import time
import uuid
from concurrent import futures
from typing import AsyncIterator

import grpc

from quantcore_strategy.generated import strategy_pb2, strategy_pb2_grpc
from quantcore_strategy.sandbox import StrategySandbox
from quantcore_strategy.scheduler import StrategyScheduler

logger = logging.getLogger(__name__)

_BACKTEST_PROGRESS_INTERVAL = 0.3


class StrategyServiceServicer(strategy_pb2_grpc.StrategyServiceServicer):
    def __init__(self) -> None:
        self._sandbox = StrategySandbox()
        self._scheduler = StrategyScheduler()
        self._backtest_progress: dict[str, dict] = {}

    async def RunBacktest(
        self,
        request: strategy_pb2.BacktestRequest,
        context: grpc.aio.ServicerContext,
    ) -> strategy_pb2.BacktestResponse:
        logger.info(
            "RunBacktest: strategy_id=%s symbols=%s",
            request.strategy_id,
            list(request.symbols),
        )

        validation = self._sandbox.validate_strategy_code(request.strategy_code)
        if not validation.is_valid:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"Strategy validation failed: {'; '.join(validation.errors)}",
            )

        backtest_id = f"bt-{uuid.uuid4().hex[:12]}"
        self._backtest_progress[backtest_id] = {
            "progress_pct": 0.0,
            "current_phase": "initializing",
            "bars_processed": 0,
            "total_bars": 1000,
        }

        sandbox_context = {
            "symbols": list(request.symbols),
            "start_date": request.start_date,
            "end_date": request.end_date,
            "initial_capital": request.initial_capital,
            "commission": request.commission,
            "slippage": request.slippage,
            "parameters": dict(request.parameters),
            "backtest_id": backtest_id,
        }

        self._backtest_progress[backtest_id]["current_phase"] = "executing"
        self._backtest_progress[backtest_id]["progress_pct"] = 0.1

        result = await self._sandbox.execute_strategy(
            code=request.strategy_code,
            context=sandbox_context,
            timeout=60.0,
        )

        self._backtest_progress[backtest_id]["progress_pct"] = 1.0
        self._backtest_progress[backtest_id]["current_phase"] = "completed"
        self._backtest_progress[backtest_id]["bars_processed"] = 1000

        if not result.get("success"):
            await context.abort(
                grpc.StatusCode.INTERNAL,
                f"Backtest execution failed: {'; '.join(result.get('errors', []))}",
            )

        data = result.get("data", {})
        metrics = data.get("metrics", {}) if isinstance(data.get("metrics"), dict) else {}
        equity_curve_raw = data.get("equity_curve", [])

        equity_points = []
        if isinstance(equity_curve_raw, (list, tuple)):
            for point in equity_curve_raw:
                if isinstance(point, dict):
                    equity_points.append(
                        strategy_pb2.EquityPoint(
                            timestamp_ns=int(point.get("timestamp_ns", 0)),
                            equity=float(point.get("equity", 0.0)),
                            drawdown=float(point.get("drawdown", 0.0)),
                        )
                    )

        response = strategy_pb2.BacktestResponse(
            backtest_id=backtest_id,
            total_return=float(metrics.get("total_return", 0.0)),
            annual_return=float(metrics.get("annual_return", 0.0)),
            sharpe_ratio=float(metrics.get("sharpe_ratio", 0.0)),
            max_drawdown=float(metrics.get("max_drawdown", 0.0)),
            win_rate=float(metrics.get("win_rate", 0.0)),
            profit_factor=float(metrics.get("profit_factor", 0.0)),
            total_trades=int(metrics.get("total_trades", 0)),
            avg_trade_return=float(metrics.get("avg_trade_return", 0.0)),
            calmar_ratio=float(metrics.get("calmar_ratio", 0.0)),
            equity_curve=equity_points,
        )

        logger.info(
            "Backtest complete: backtest_id=%s total_return=%.4f sharpe=%.4f",
            backtest_id,
            response.total_return,
            response.sharpe_ratio,
        )
        return response

    async def StreamBacktestProgress(
        self,
        request: strategy_pb2.BacktestProgressRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[strategy_pb2.BacktestProgress]:
        backtest_id = request.backtest_id
        logger.info("StreamBacktestProgress: backtest_id=%s", backtest_id)

        while not context.cancelled():
            progress = self._backtest_progress.get(backtest_id)
            if progress is None:
                await context.abort(
                    grpc.StatusCode.NOT_FOUND,
                    f"Backtest '{backtest_id}' not found",
                )

            yield strategy_pb2.BacktestProgress(
                backtest_id=backtest_id,
                progress_pct=progress["progress_pct"],
                current_phase=progress["current_phase"],
                bars_processed=progress["bars_processed"],
                total_bars=progress["total_bars"],
            )

            if progress["progress_pct"] >= 1.0:
                break

            await asyncio.sleep(_BACKTEST_PROGRESS_INTERVAL)

    async def DeployStrategy(
        self,
        request: strategy_pb2.DeployStrategyRequest,
        context: grpc.aio.ServicerContext,
    ) -> strategy_pb2.DeployStrategyResponse:
        logger.info(
            "DeployStrategy: strategy_id=%s symbols=%s",
            request.strategy_id,
            list(request.symbols),
        )

        validation = self._sandbox.validate_strategy_code(request.strategy_code)
        if not validation.is_valid:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"Strategy validation failed: {'; '.join(validation.errors)}",
            )

        try:
            deployment_id = await self._scheduler.deploy_strategy(
                strategy_id=request.strategy_id,
                code=request.strategy_code,
                symbols=list(request.symbols),
                params=dict(request.parameters),
            )
        except RuntimeError as e:
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                str(e),
            )

        return strategy_pb2.DeployStrategyResponse(
            success=True,
            deployment_id=deployment_id,
            message=f"Strategy '{request.strategy_id}' deployed as '{deployment_id}'",
        )

    async def StopStrategy(
        self,
        request: strategy_pb2.StopStrategyRequest,
        context: grpc.aio.ServicerContext,
    ) -> strategy_pb2.StopStrategyResponse:
        logger.info("StopStrategy: deployment_id=%s", request.deployment_id)

        success = await self._scheduler.stop_strategy(request.deployment_id)
        if not success:
            await context.abort(
                grpc.StatusCode.NOT_FOUND,
                f"Deployment '{request.deployment_id}' not found or not running",
            )

        return strategy_pb2.StopStrategyResponse(
            success=True,
            message=f"Deployment '{request.deployment_id}' stopped",
        )

    async def ListStrategies(
        self,
        request: strategy_pb2.ListStrategiesRequest,
        context: grpc.aio.ServicerContext,
    ) -> strategy_pb2.ListStrategiesResponse:
        logger.info("ListStrategies: account_id=%s", request.account_id)

        strategies = self._scheduler.list_strategies()

        if request.active_only:
            strategies = [s for s in strategies if s.status == "running"]

        return strategy_pb2.ListStrategiesResponse(
            strategies=[
                strategy_pb2.StrategyInfo(
                    deployment_id=s.deployment_id,
                    strategy_id=s.strategy_id,
                    status=s.status,
                    started_at_ns=s.started_at_ns,
                    pnl=s.pnl,
                    trade_count=s.trade_count,
                )
                for s in strategies
            ]
        )

    async def GetStrategyStatus(
        self,
        request: strategy_pb2.StrategyStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> strategy_pb2.StrategyStatusResponse:
        logger.info("GetStrategyStatus: deployment_id=%s", request.deployment_id)

        status = self._scheduler.get_strategy_status(request.deployment_id)
        if status is None:
            await context.abort(
                grpc.StatusCode.NOT_FOUND,
                f"Deployment '{request.deployment_id}' not found",
            )

        return strategy_pb2.StrategyStatusResponse(
            deployment_id=status.deployment_id,
            strategy_id=status.strategy_id,
            status=status.status,
            current_pnl=status.current_pnl,
            trade_count=status.trade_count,
            sharpe_ratio=status.sharpe_ratio,
            max_drawdown=status.max_drawdown,
            active_positions=status.active_positions,
            started_at_ns=status.started_at_ns,
        )

    async def graceful_shutdown(self) -> None:
        logger.info("StrategyServiceServicer: initiating graceful shutdown")
        await self._scheduler.shutdown()


async def serve(port: int = 50054) -> tuple[grpc.aio.Server, StrategyServiceServicer]:
    server = grpc.aio.Server(
        futures.ThreadPoolExecutor(max_workers=10),
        options=[
            ("grpc.max_receive_message_length", 64 * 1024 * 1024),
            ("grpc.max_send_message_length", 64 * 1024 * 1024),
            ("grpc.keepalive_time_ms", 30000),
            ("grpc.keepalive_timeout_ms", 10000),
        ],
    )

    servicer = StrategyServiceServicer()
    strategy_pb2_grpc.add_StrategyServiceServicer_to_server(servicer, server)

    listen_addr = f"[::]:{port}"
    server.add_insecure_port(listen_addr)
    await server.start()

    logger.info("Strategy Engine gRPC server started on %s", listen_addr)
    return server, servicer
