import itertools
import logging
import queue
import time
import uuid
from concurrent import futures
from typing import Any

import grpc
import numpy as np

from generated import backtest_pb2, backtest_pb2_grpc
from quantcore_backtest.gpu_accel import GPUAccelerator
from quantcore_backtest.parallel import ParallelBacktester
from quantcore_backtest.tick_engine import BacktestResult, SlippageModel, TickLevelBacktester

logger = logging.getLogger(__name__)

_SLIPPAGE_MODEL_MAP: dict[str, SlippageModel] = {
    "linear": SlippageModel.LINEAR,
    "square_root": SlippageModel.SQUARE_ROOT,
    "proportional": SlippageModel.PROPORTIONAL,
    "": SlippageModel.SQUARE_ROOT,
}


def _result_to_response(result: BacktestResult, gpu_accelerated: bool = False) -> backtest_pb2.TickBacktestResponse:
    equity_points = []
    step = max(1, len(result.equity_curve) // 500)
    for i in range(0, len(result.equity_curve), step):
        equity_points.append(backtest_pb2.EquityPoint(
            timestamp_ns=0,
            equity=result.equity_curve[i],
            drawdown=0.0,
        ))

    total_return = (result.equity_curve[-1] / result.equity_curve[0] - 1.0) if result.equity_curve and result.equity_curve[0] > 0 else 0.0
    annual_return = ((result.equity_curve[-1] / result.equity_curve[0]) ** (252 / max(len(result.equity_curve) - 1, 1)) - 1) if result.equity_curve and len(result.equity_curve) > 1 and result.equity_curve[0] > 0 else 0.0

    return backtest_pb2.TickBacktestResponse(
        backtest_id=result.backtest_id,
        total_return=total_return,
        annual_return=annual_return,
        sharpe_ratio=result.metrics.sharpe,
        sortino_ratio=result.metrics.sortino,
        max_drawdown=result.metrics.max_drawdown,
        win_rate=result.metrics.win_rate,
        profit_factor=result.metrics.profit_factor,
        total_trades=result.metrics.total_trades,
        avg_trade_return=result.metrics.avg_trade_return,
        calmar_ratio=result.metrics.calmar_ratio,
        equity_curve=equity_points,
        gpu_accelerated=gpu_accelerated,
    )


def _build_strategy_fn(strategy_code: str, parameters: dict[str, str]) -> Any:
    namespace: dict[str, Any] = {}
    try:
        exec(strategy_code, namespace)
        fn = namespace.get("strategy_fn") or namespace.get("on_tick")
        if fn is not None:
            return fn
    except Exception:
        logger.exception("Failed to compile strategy_code; using no-op strategy")

    def _noop_strategy(tick: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        return {}

    return _noop_strategy


class BacktestServiceServicer(backtest_pb2_grpc.BacktestServiceServicer):
    def __init__(self) -> None:
        self._gpu = GPUAccelerator()
        self._progress_queues: dict[str, queue.Queue] = {}
        self._backtester = TickLevelBacktester()
        logger.info(
            "BacktestServiceServicer initialized (gpu_available=%s)",
            self._gpu.gpu_available,
        )

    def RunTickBacktest(
        self,
        request: backtest_pb2.TickBacktestRequest,
        context: grpc.ServicerContext,
    ) -> backtest_pb2.TickBacktestResponse:
        backtest_id = uuid.uuid4().hex[:12]
        logger.info("RunTickBacktest: id=%s strategy=%s", backtest_id, request.strategy_id)

        try:
            strategy_fn = _build_strategy_fn(request.strategy_code, dict(request.parameters))
        except Exception as e:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(f"Invalid strategy code: {e}")
            return backtest_pb2.TickBacktestResponse(backtest_id=backtest_id)

        slippage_model = _SLIPPAGE_MODEL_MAP.get(request.slippage_model, SlippageModel.SQUARE_ROOT)

        backtester = TickLevelBacktester(
            commission=request.commission,
            slippage_model=slippage_model,
            slippage_base_bps=request.slippage_base_bps,
            slippage_impact_coeff=request.slippage_impact_coeff,
        )

        ticks = self._mock_ticks_from_request(request)

        result = backtester.run(
            ticks=ticks,
            strategy_fn=strategy_fn,
            initial_capital=request.initial_capital,
        )

        return _result_to_response(result, gpu_accelerated=self._gpu.gpu_available)

    def StreamBacktestProgress(
        self,
        request: backtest_pb2.BacktestProgressRequest,
        context: grpc.ServicerContext,
    ) -> Any:
        backtest_id = request.backtest_id
        logger.info("StreamBacktestProgress: id=%s", backtest_id)

        progress_q = self._progress_queues.get(backtest_id)
        if progress_q is None:
            progress_q = queue.Queue()
            self._progress_queues[backtest_id] = progress_q

        total_ticks = 0
        ticks_processed = 0

        while context.is_active():
            try:
                update = progress_q.get(timeout=0.5)
                if update is None:
                    break
                ticks_processed = update.get("ticks_processed", ticks_processed)
                total_ticks = update.get("total_ticks", total_ticks)
            except queue.Empty:
                pass

            progress_pct = (ticks_processed / total_ticks * 100) if total_ticks > 0 else 0.0
            yield backtest_pb2.BacktestProgress(
                backtest_id=backtest_id,
                progress_pct=progress_pct,
                current_phase="processing",
                ticks_processed=ticks_processed,
                total_ticks=total_ticks,
            )

            if total_ticks > 0 and ticks_processed >= total_ticks:
                break

        self._progress_queues.pop(backtest_id, None)

    def RunBatchBacktest(
        self,
        request: backtest_pb2.BatchBacktestRequest,
        context: grpc.ServicerContext,
    ) -> backtest_pb2.BatchBacktestResponse:
        logger.info("RunBatchBacktest: %d strategies", len(request.strategies))

        strategies: list[dict[str, Any]] = []
        for cfg in request.strategies:
            strategy_fn = _build_strategy_fn(cfg.strategy_code, dict(cfg.parameters))
            strategies.append({
                "strategy_fn": strategy_fn,
                "backtester_kwargs": {
                    "commission": request.commission,
                    "slippage_base_bps": 1.0,
                    "slippage_impact_coeff": 0.1,
                },
            })

        ticks = self._mock_ticks_from_batch_request(request)

        with ParallelBacktester() as parallel:
            results = parallel.run_parallel(
                strategies=strategies,
                ticks=ticks,
                initial_capital=request.initial_capital,
            )

        proto_results = [_result_to_response(r, self._gpu.gpu_available) for r in results]
        return backtest_pb2.BatchBacktestResponse(results=proto_results)

    def RunParamSweep(
        self,
        request: backtest_pb2.ParamSweepRequest,
        context: grpc.ServicerContext,
    ) -> backtest_pb2.ParamSweepResponse:
        logger.info("RunParamSweep: %d param ranges", len(request.param_ranges))

        base_cfg = request.base_strategy
        strategy_fn = _build_strategy_fn(base_cfg.strategy_code, dict(base_cfg.parameters))

        param_grid: dict[str, list[Any]] = {}
        param_combinations: list[str] = []
        for pr in request.param_ranges:
            values = []
            v = pr.min_value
            while v <= pr.max_value + pr.step * 0.01:
                values.append(v)
                v += pr.step
            param_grid[pr.name] = values

        keys = list(param_grid.keys())
        for combo in itertools.product(*param_grid.values()):
            param_combinations.append(
                ", ".join(f"{k}={v}" for k, v in zip(keys, combo, strict=True))
            )

        base_strategy = {
            "strategy_fn": strategy_fn,
            "backtester_kwargs": {
                "commission": request.commission,
                "slippage_base_bps": 1.0,
                "slippage_impact_coeff": 0.1,
            },
        }

        ticks = self._mock_ticks_from_sweep_request(request)

        with ParallelBacktester() as parallel:
            results = parallel.run_param_sweep(
                base_strategy=base_strategy,
                param_grid=param_grid,
                ticks=ticks,
                initial_capital=request.initial_capital,
            )

        proto_results = [_result_to_response(r, self._gpu.gpu_available) for r in results]
        return backtest_pb2.ParamSweepResponse(
            results=proto_results,
            param_combinations=param_combinations,
        )

    @staticmethod
    def _mock_ticks_from_request(request: backtest_pb2.TickBacktestRequest) -> list[dict[str, Any]]:
        rng = np.random.default_rng(42)
        n = 1000
        base_price = 100.0
        prices = base_price + rng.standard_normal(n).cumsum() * 0.05
        prices = np.maximum(prices, 1.0)
        start_ns = request.start_timestamp_ns or int(time.time() * 1e9)
        return [
            {
                "timestamp_ns": start_ns + i * 1_000_000,
                "symbol": request.symbols[0] if request.symbols else "MOCK",
                "price": float(prices[i]),
                "size": int(rng.integers(100, 10000)),
                "bid_price": float(prices[i] - 0.01),
                "ask_price": float(prices[i] + 0.01),
                "side": "buy" if i % 2 == 0 else "sell",
            }
            for i in range(n)
        ]

    @staticmethod
    def _mock_ticks_from_batch_request(request: backtest_pb2.BatchBacktestRequest) -> list[dict[str, Any]]:
        rng = np.random.default_rng(42)
        n = 500
        base_price = 100.0
        prices = base_price + rng.standard_normal(n).cumsum() * 0.05
        prices = np.maximum(prices, 1.0)
        start_ns = int(time.time() * 1e9)
        return [
            {
                "timestamp_ns": start_ns + i * 1_000_000,
                "symbol": "MOCK",
                "price": float(prices[i]),
                "size": int(rng.integers(100, 10000)),
                "bid_price": float(prices[i] - 0.01),
                "ask_price": float(prices[i] + 0.01),
                "side": "buy" if i % 2 == 0 else "sell",
            }
            for i in range(n)
        ]

    @staticmethod
    def _mock_ticks_from_sweep_request(request: backtest_pb2.ParamSweepRequest) -> list[dict[str, Any]]:
        rng = np.random.default_rng(42)
        n = 500
        base_price = 100.0
        prices = base_price + rng.standard_normal(n).cumsum() * 0.05
        prices = np.maximum(prices, 1.0)
        start_ns = int(time.time() * 1e9)
        return [
            {
                "timestamp_ns": start_ns + i * 1_000_000,
                "symbol": "MOCK",
                "price": float(prices[i]),
                "size": int(rng.integers(100, 10000)),
                "bid_price": float(prices[i] - 0.01),
                "ask_price": float(prices[i] + 0.01),
                "side": "buy" if i % 2 == 0 else "sell",
            }
            for i in range(n)
        ]


def create_server(port: int = 50056, max_workers: int = 10) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    servicer = BacktestServiceServicer()
    backtest_pb2_grpc.add_BacktestServiceServicer_to_server(servicer, server)
    server.add_insecure_port(f"[::]:{port}")
    logger.info("Backtest gRPC server configured on port %d with %d workers", port, max_workers)
    return server
