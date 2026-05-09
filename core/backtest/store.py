import json
import logging
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .analysis import compare_results
from .result import BacktestResult

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
RESULTS_DIR = DATA_DIR / "backtest_results"

_SERIALIZABLE_FIELDS = frozenset({
    "strategy_name", "total_return", "annual_return", "sharpe_ratio",
    "max_drawdown", "calmar_ratio", "win_rate", "profit_factor",
    "total_trades", "win_trades", "loss_trades", "avg_profit", "avg_loss",
    "avg_hold_days", "benchmark_return", "alpha", "beta",
    "sortino_ratio", "max_consecutive_losses", "omega_ratio", "tail_ratio",
    "information_ratio", "recovery_factor", "avg_mae", "avg_mfe",
    "cvar_95", "var_95", "annual_volatility", "downside_deviation",
    "expectancy", "payoff_ratio",
})


class BacktestResultStore:
    """回测结果持久化，支持跨 session 对比"""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self._base_dir = Path(base_dir) if base_dir else RESULTS_DIR
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        result: BacktestResult,
        symbol: str,
        strategy_name: str,
        params: dict | None = None,
    ) -> str:
        result_id = uuid.uuid4().hex[:16]
        payload: dict[str, Any] = {
            "result_id": result_id,
            "symbol": symbol,
            "strategy_name": strategy_name,
            "params": params or {},
            "saved_at": datetime.now().isoformat(),
            "metrics": self._extract_metrics(result),
        }
        path = self._base_dir / f"{result_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, default=str)
        logger.debug("Saved backtest result %s for %s/%s", result_id, symbol, strategy_name)
        return result_id

    def load(self, result_id: str) -> BacktestResult | None:
        path = self._base_dir / f"{result_id}.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        metrics = payload.get("metrics", {})
        return BacktestResult(
            strategy_name=metrics.get("strategy_name", payload.get("strategy_name", "")),
            total_return=metrics.get("total_return", 0.0),
            annual_return=metrics.get("annual_return", 0.0),
            sharpe_ratio=metrics.get("sharpe_ratio", 0.0),
            max_drawdown=metrics.get("max_drawdown", 0.0),
            calmar_ratio=metrics.get("calmar_ratio", 0.0),
            win_rate=metrics.get("win_rate", 0.0),
            profit_factor=metrics.get("profit_factor", 0.0),
            total_trades=metrics.get("total_trades", 0),
            win_trades=metrics.get("win_trades", 0),
            loss_trades=metrics.get("loss_trades", 0),
            avg_profit=metrics.get("avg_profit", 0.0),
            avg_loss=metrics.get("avg_loss", 0.0),
            avg_hold_days=metrics.get("avg_hold_days", 0.0),
            benchmark_return=metrics.get("benchmark_return", 0.0),
            alpha=metrics.get("alpha", 0.0),
            beta=metrics.get("beta", 1.0),
            sortino_ratio=metrics.get("sortino_ratio", 0.0),
            max_consecutive_losses=metrics.get("max_consecutive_losses", 0),
            omega_ratio=metrics.get("omega_ratio", 0.0),
            tail_ratio=metrics.get("tail_ratio", 0.0),
            information_ratio=metrics.get("information_ratio", 0.0),
            recovery_factor=metrics.get("recovery_factor", 0.0),
            avg_mae=metrics.get("avg_mae", 0.0),
            avg_mfe=metrics.get("avg_mfe", 0.0),
            cvar_95=metrics.get("cvar_95", 0.0),
            var_95=metrics.get("var_95", 0.0),
            annual_volatility=metrics.get("annual_volatility", 0.0),
            downside_deviation=metrics.get("downside_deviation", 0.0),
            expectancy=metrics.get("expectancy", 0.0),
            payoff_ratio=metrics.get("payoff_ratio", 0.0),
        )

    def compare(self, result_ids: list[str]) -> dict:
        results = [r for rid in result_ids if (r := self.load(rid)) is not None]
        if not results:
            return {"error": "No valid results found for comparison"}
        return compare_results(results)

    def get_history(self, symbol: str = "", limit: int = 20) -> list[dict]:
        entries: list[dict] = []
        for path in sorted(self._base_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if len(entries) >= limit:
                break
            try:
                with open(path, encoding="utf-8") as f:
                    payload = json.load(f)
                if symbol and payload.get("symbol") != symbol:
                    continue
                entries.append({
                    "result_id": payload.get("result_id", path.stem),
                    "symbol": payload.get("symbol", ""),
                    "strategy_name": payload.get("strategy_name", ""),
                    "params": payload.get("params", {}),
                    "saved_at": payload.get("saved_at", ""),
                    "sharpe_ratio": payload.get("metrics", {}).get("sharpe_ratio", 0),
                    "total_return": payload.get("metrics", {}).get("total_return", 0),
                    "max_drawdown": payload.get("metrics", {}).get("max_drawdown", 0),
                })
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("Skipping corrupt result file %s: %s", path, e)
        return entries

    def delete(self, result_id: str) -> bool:
        path = self._base_dir / f"{result_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    @staticmethod
    def _extract_metrics(result: BacktestResult) -> dict[str, Any]:
        return {field: getattr(result, field, 0) for field in _SERIALIZABLE_FIELDS}
