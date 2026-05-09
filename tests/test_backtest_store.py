import json
import tempfile
from pathlib import Path

import pytest

from core.backtest.result import BacktestResult
from core.backtest.store import BacktestResultStore


@pytest.fixture
def store(tmp_path: Path) -> BacktestResultStore:
    return BacktestResultStore(base_dir=tmp_path)


@pytest.fixture
def sample_result() -> BacktestResult:
    return BacktestResult(
        strategy_name="TestStrategy",
        total_return=0.15,
        annual_return=0.12,
        sharpe_ratio=1.5,
        max_drawdown=0.08,
        calmar_ratio=1.8,
        win_rate=0.6,
        profit_factor=2.0,
        total_trades=50,
        win_trades=30,
        loss_trades=20,
    )


class TestBacktestResultStore:
    def test_save_returns_result_id(self, store: BacktestResultStore, sample_result: BacktestResult) -> None:
        result_id = store.save(sample_result, "000001.SZ", "TestStrategy", {"period": 20})
        assert isinstance(result_id, str)
        assert len(result_id) == 16

    def test_save_creates_file(self, store: BacktestResultStore, sample_result: BacktestResult) -> None:
        result_id = store.save(sample_result, "000001.SZ", "TestStrategy")
        path = store._base_dir / f"{result_id}.json"
        assert path.exists()

    def test_save_file_contains_expected_fields(self, store: BacktestResultStore, sample_result: BacktestResult) -> None:
        result_id = store.save(sample_result, "000001.SZ", "TestStrategy", {"period": 20})
        path = store._base_dir / f"{result_id}.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["symbol"] == "000001.SZ"
        assert data["strategy_name"] == "TestStrategy"
        assert data["params"] == {"period": 20}
        assert data["metrics"]["sharpe_ratio"] == 1.5
        assert "saved_at" in data

    def test_load_returns_backtest_result(self, store: BacktestResultStore, sample_result: BacktestResult) -> None:
        result_id = store.save(sample_result, "000001.SZ", "TestStrategy")
        loaded = store.load(result_id)
        assert loaded is not None
        assert loaded.strategy_name == "TestStrategy"
        assert loaded.sharpe_ratio == 1.5
        assert loaded.total_return == 0.15

    def test_load_nonexistent_returns_none(self, store: BacktestResultStore) -> None:
        result = store.load("nonexistent_id")
        assert result is None

    def test_compare_two_results(self, store: BacktestResultStore) -> None:
        r1 = BacktestResult(strategy_name="StrategyA", sharpe_ratio=1.5, total_return=0.2)
        r2 = BacktestResult(strategy_name="StrategyB", sharpe_ratio=0.8, total_return=0.1)
        id1 = store.save(r1, "000001.SZ", "StrategyA")
        id2 = store.save(r2, "000001.SZ", "StrategyB")
        comparison = store.compare([id1, id2])
        assert "ranking" in comparison
        assert len(comparison["ranking"]) == 2
        assert comparison["ranking"][0]["strategy_name"] == "StrategyA"

    def test_compare_empty_ids(self, store: BacktestResultStore) -> None:
        comparison = store.compare(["nonexistent"])
        assert "error" in comparison

    def test_get_history_returns_entries(self, store: BacktestResultStore, sample_result: BacktestResult) -> None:
        store.save(sample_result, "000001.SZ", "TestStrategy")
        store.save(sample_result, "000001.SZ", "TestStrategy2")
        history = store.get_history(symbol="000001.SZ")
        assert len(history) == 2

    def test_get_history_filters_by_symbol(self, store: BacktestResultStore, sample_result: BacktestResult) -> None:
        store.save(sample_result, "000001.SZ", "TestStrategy")
        store.save(sample_result, "600000.SH", "TestStrategy")
        history = store.get_history(symbol="000001.SZ")
        assert len(history) == 1
        assert history[0]["symbol"] == "000001.SZ"

    def test_get_history_respects_limit(self, store: BacktestResultStore, sample_result: BacktestResult) -> None:
        for i in range(5):
            store.save(sample_result, "000001.SZ", f"Strategy{i}")
        history = store.get_history(symbol="000001.SZ", limit=3)
        assert len(history) == 3

    def test_get_history_no_symbol_filter(self, store: BacktestResultStore, sample_result: BacktestResult) -> None:
        store.save(sample_result, "000001.SZ", "TestStrategy")
        store.save(sample_result, "600000.SH", "TestStrategy")
        history = store.get_history()
        assert len(history) == 2

    def test_delete_existing(self, store: BacktestResultStore, sample_result: BacktestResult) -> None:
        result_id = store.save(sample_result, "000001.SZ", "TestStrategy")
        assert store.delete(result_id) is True
        assert store.load(result_id) is None

    def test_delete_nonexistent(self, store: BacktestResultStore) -> None:
        assert store.delete("nonexistent") is False

    def test_save_and_load_preserves_numeric_fields(self, store: BacktestResultStore) -> None:
        result = BacktestResult(
            strategy_name="FullResult",
            total_return=0.25,
            annual_return=0.18,
            sharpe_ratio=2.1,
            max_drawdown=0.12,
            calmar_ratio=1.5,
            win_rate=0.65,
            profit_factor=2.5,
            total_trades=100,
            win_trades=65,
            loss_trades=35,
            avg_profit=0.03,
            avg_loss=-0.02,
            avg_hold_days=5.5,
            benchmark_return=0.10,
            alpha=0.08,
            beta=0.95,
            sortino_ratio=2.8,
            omega_ratio=1.6,
            tail_ratio=1.2,
            information_ratio=0.9,
            recovery_factor=3.0,
            avg_mae=0.015,
            avg_mfe=0.025,
            cvar_95=0.04,
            var_95=0.03,
            annual_volatility=0.15,
            downside_deviation=0.10,
            expectancy=0.01,
            payoff_ratio=1.5,
        )
        result_id = store.save(result, "000001.SZ", "FullResult")
        loaded = store.load(result_id)
        assert loaded is not None
        assert loaded.sharpe_ratio == 2.1
        assert loaded.total_return == 0.25
        assert loaded.total_trades == 100
        assert loaded.beta == 0.95
