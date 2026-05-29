import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from quantcore_strategy.sandbox import StrategySandbox
import contextlib

logger = logging.getLogger(__name__)


class StrategyState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class StrategyInfo:
    deployment_id: str
    strategy_id: str
    status: str
    started_at_ns: int
    pnl: float = 0.0
    trade_count: int = 0


@dataclass
class StrategyStatus:
    deployment_id: str
    strategy_id: str
    status: str
    current_pnl: float = 0.0
    trade_count: int = 0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    active_positions: list[str] = field(default_factory=list)
    started_at_ns: int = 0


@dataclass
class _DeploymentRecord:
    deployment_id: str
    strategy_id: str
    code: str
    symbols: list[str]
    params: dict[str, str]
    state: StrategyState = StrategyState.PENDING
    started_at_ns: int = 0
    pnl: float = 0.0
    trade_count: int = 0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    active_positions: list[str] = field(default_factory=list)
    task: Optional[asyncio.Task] = field(default=None, repr=False)


class StrategyScheduler:
    def __init__(self, max_concurrent: int = 20) -> None:
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running: dict[str, asyncio.Task] = {}
        self._deployments: dict[str, _DeploymentRecord] = {}
        self._sandbox = StrategySandbox()

    async def deploy_strategy(
        self,
        strategy_id: str,
        code: str,
        symbols: list[str],
        params: dict[str, str],
    ) -> str:
        if len(self._running) >= self._max_concurrent:
            raise RuntimeError(
                f"Maximum concurrent strategies reached ({self._max_concurrent})"
            )

        deployment_id = f"deploy-{uuid.uuid4().hex[:12]}"

        record = _DeploymentRecord(
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            code=code,
            symbols=symbols,
            params=params,
        )
        self._deployments[deployment_id] = record

        task = asyncio.create_task(
            self._run_strategy(deployment_id),
            name=f"strategy-{deployment_id}",
        )
        self._running[deployment_id] = task
        record.task = task

        logger.info(
            "Deployed strategy '%s' as '%s' with symbols=%s",
            strategy_id,
            deployment_id,
            symbols,
        )
        return deployment_id

    async def _run_strategy(self, deployment_id: str) -> None:
        record = self._deployments.get(deployment_id)
        if record is None:
            logger.error("Deployment '%s' not found", deployment_id)
            return

        record.state = StrategyState.RUNNING
        record.started_at_ns = time.time_ns()

        try:
            async with self._semaphore:
                context: dict[str, Any] = {
                    "symbols": record.symbols,
                    "params": record.params,
                    "deployment_id": deployment_id,
                }
                result = await self._sandbox.execute_strategy(
                    code=record.code,
                    context=context,
                    timeout=60.0,
                )

                if result.get("success"):
                    data = result.get("data", {})
                    record.pnl = float(data.get("metrics", {}).get("pnl", 0.0))
                    record.trade_count = int(data.get("metrics", {}).get("trade_count", 0))
                    record.sharpe_ratio = float(
                        data.get("metrics", {}).get("sharpe_ratio", 0.0)
                    )
                    record.max_drawdown = float(
                        data.get("metrics", {}).get("max_drawdown", 0.0)
                    )
                    record.active_positions = list(
                        data.get("positions", {}).get("active", [])
                    )
                else:
                    record.state = StrategyState.ERROR
                    logger.error(
                        "Strategy '%s' execution failed: %s",
                        deployment_id,
                        result.get("errors", []),
                    )
                    return

        except asyncio.CancelledError:
            record.state = StrategyState.STOPPED
            logger.info("Strategy '%s' was stopped", deployment_id)
            return
        except Exception:
            record.state = StrategyState.ERROR
            logger.exception("Strategy '%s' failed with exception", deployment_id)
            return

        record.state = StrategyState.STOPPED
        self._running.pop(deployment_id, None)

    async def stop_strategy(self, deployment_id: str) -> bool:
        task = self._running.get(deployment_id)
        if task is None:
            logger.warning("No running task for deployment '%s'", deployment_id)
            return False

        task.cancel()
        with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=10.0)

        self._running.pop(deployment_id, None)

        record = self._deployments.get(deployment_id)
        if record:
            record.state = StrategyState.STOPPED

        logger.info("Stopped strategy deployment '%s'", deployment_id)
        return True

    def list_strategies(self) -> list[StrategyInfo]:
        return [
            StrategyInfo(
                deployment_id=rec.deployment_id,
                strategy_id=rec.strategy_id,
                status=rec.state.value,
                started_at_ns=rec.started_at_ns,
                pnl=rec.pnl,
                trade_count=rec.trade_count,
            )
            for rec in self._deployments.values()
        ]

    def get_strategy_status(self, deployment_id: str) -> Optional[StrategyStatus]:
        record = self._deployments.get(deployment_id)
        if record is None:
            return None

        return StrategyStatus(
            deployment_id=record.deployment_id,
            strategy_id=record.strategy_id,
            status=record.state.value,
            current_pnl=record.pnl,
            trade_count=record.trade_count,
            sharpe_ratio=record.sharpe_ratio,
            max_drawdown=record.max_drawdown,
            active_positions=list(record.active_positions),
            started_at_ns=record.started_at_ns,
        )

    @property
    def active_count(self) -> int:
        return len(self._running)

    async def shutdown(self) -> None:
        deployment_ids = list(self._running.keys())
        if deployment_ids:
            results = await asyncio.gather(
                *(self.stop_strategy(did) for did in deployment_ids),
                return_exceptions=True,
            )
            for did, result in zip(deployment_ids, results, strict=False):
                if isinstance(result, Exception):
                    logger.error("Error stopping deployment '%s': %s", did, result)
        logger.info("StrategyScheduler shutdown complete")
