import numpy as np
import pandas as pd
import pytest

from core.backtest.validation import (
    walk_forward_ic_validation,
    walk_forward_oos_validation,
    WalkForwardICResult,
    ICWindowResult,
    _extract_signal_return_pairs,
    _compute_ic_summary,
    _determine_ic_verdict,
)
from core.strategies import DualMAStrategy


def _make_df(n: int = 600) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    close = np.cumsum(rng.normal(0.05, 1.5, n)) + 100
    return pd.DataFrame({
        "date": dates,
        "open": close - 0.5,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": rng.integers(1000, 10000, n),
    })


class TestWalkForwardICValidation:

    def test_insufficient_data_returns_result(self):
        result = walk_forward_ic_validation(DualMAStrategy, _make_df(50))
        assert isinstance(result, WalkForwardICResult)
        assert "error" in result.base_result

    def test_none_df_returns_result(self):
        result = walk_forward_ic_validation(DualMAStrategy, None)
        assert isinstance(result, WalkForwardICResult)

    def test_sufficient_data_produces_windows(self):
        df = _make_df(800)
        result = walk_forward_ic_validation(
            DualMAStrategy, df, train_days=200, test_days=60,
        )
        assert isinstance(result, WalkForwardICResult)
        assert result.base_result.get("windows")
        assert isinstance(result.ic_windows, list)

    def test_ic_verdict_is_string(self):
        df = _make_df(800)
        result = walk_forward_ic_validation(
            DualMAStrategy, df, train_days=200, test_days=60,
        )
        assert isinstance(result.ic_verdict, str)
        assert result.ic_verdict in (
            "robust", "moderate", "overfit", "marginal",
            "ic_decaying", "factor_invalid", "strategy_degrading",
            "insufficient_data", "unknown",
        )

    def test_ic_summary_structure(self):
        df = _make_df(800)
        result = walk_forward_ic_validation(
            DualMAStrategy, df, train_days=200, test_days=60,
        )
        summary = result.ic_summary
        assert "mean_ic" in summary
        assert "mean_rank_ic" in summary
        assert "ic_ir" in summary
        assert "decay_rate" in summary
        assert "valid_windows" in summary
        assert "total_windows" in summary

    def test_model_status_structure(self):
        df = _make_df(800)
        result = walk_forward_ic_validation(
            DualMAStrategy, df, train_days=200, test_days=60,
        )
        status = result.model_status
        assert "status" in status
        assert "mean_rank_ic" in status

    def test_base_result_preserved(self):
        df = _make_df(800)
        result = walk_forward_ic_validation(
            DualMAStrategy, df, train_days=200, test_days=60,
        )
        base = result.base_result
        assert "windows" in base
        assert "summary" in base
        assert "verdict" in base

    def test_with_param_grid(self):
        df = _make_df(800)
        result = walk_forward_ic_validation(
            DualMAStrategy, df,
            train_days=200, test_days=60,
            param_grid={"short_period": [3, 5], "long_period": [10, 20]},
        )
        assert isinstance(result, WalkForwardICResult)


class TestICWindowResult:

    def test_dataclass_fields(self):
        w = ICWindowResult(
            window=0, ic=0.05, rank_ic=0.04, ic_ir=1.2,
            n_observations=30, factor_valid=True,
            weight_adjustment=1.0, position_scale=1.0,
        )
        assert w.window == 0
        assert w.ic == 0.05
        assert w.factor_valid is True


class TestComputeICSummary:

    def test_empty_windows(self):
        summary = _compute_ic_summary([])
        assert summary["mean_ic"] == 0.0
        assert summary["total_windows"] == 0

    def test_with_windows(self):
        windows = [
            ICWindowResult(0, 0.05, 0.04, 1.2, 30, True, 1.0, 1.0),
            ICWindowResult(1, 0.03, 0.02, 0.8, 25, True, 0.9, 1.0),
            ICWindowResult(2, 0.01, 0.01, 0.5, 28, False, 0.5, 0.7),
            ICWindowResult(3, -0.02, -0.01, -0.3, 22, False, 0.3, 0.5),
        ]
        summary = _compute_ic_summary(windows)
        assert summary["total_windows"] == 4
        assert summary["valid_windows"] == 2
        assert summary["validity_rate"] == 0.5
        assert summary["decay_rate"] < 0

    def test_decay_rate_computed(self):
        windows = [
            ICWindowResult(0, 0.08, 0.07, 2.0, 30, True, 1.5, 1.0),
            ICWindowResult(1, 0.06, 0.05, 1.5, 30, True, 1.2, 1.0),
            ICWindowResult(2, 0.02, 0.01, 0.5, 30, False, 0.6, 0.7),
            ICWindowResult(3, -0.01, -0.02, -0.3, 30, False, 0.3, 0.5),
        ]
        summary = _compute_ic_summary(windows)
        assert summary["decay_rate"] < -0.03


class TestDetermineICVerdict:

    def test_insufficient_data(self):
        verdict = _determine_ic_verdict({"total_windows": 0}, {})
        assert verdict == "insufficient_data"

    def test_strategy_degrading(self):
        verdict = _determine_ic_verdict(
            {"total_windows": 4, "mean_ic": 0.005, "decay_rate": -0.03, "validity_rate": 0.2},
            {"verdict": "overfit"},
        )
        assert verdict == "strategy_degrading"

    def test_ic_decaying(self):
        verdict = _determine_ic_verdict(
            {"total_windows": 4, "mean_ic": 0.04, "decay_rate": -0.06, "validity_rate": 0.5},
            {"verdict": "moderate"},
        )
        assert verdict == "ic_decaying"

    def test_factor_invalid(self):
        verdict = _determine_ic_verdict(
            {"total_windows": 4, "mean_ic": 0.02, "decay_rate": -0.01, "validity_rate": 0.2},
            {"verdict": "moderate"},
        )
        assert verdict == "factor_invalid"

    def test_robust(self):
        verdict = _determine_ic_verdict(
            {"total_windows": 4, "mean_ic": 0.05, "decay_rate": 0.01, "validity_rate": 0.8},
            {"verdict": "robust"},
        )
        assert verdict == "robust"

    def test_overfit(self):
        verdict = _determine_ic_verdict(
            {"total_windows": 4, "mean_ic": 0.04, "decay_rate": -0.01, "validity_rate": 0.5},
            {"verdict": "overfit"},
        )
        assert verdict == "overfit"
