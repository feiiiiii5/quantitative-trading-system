import numpy as np
import pytest

from core.black_litterman_ic import BlackLittermanIC, BLView, BLResult


class TestBLView:

    def test_creation(self):
        view = BLView(asset_index=0, expected_return=0.05, confidence=2.0)
        assert view.asset_index == 0
        assert view.expected_return == 0.05
        assert view.confidence == 2.0


class TestBlackLittermanIC:

    @pytest.fixture()
    def sample_cov(self):
        return np.array([
            [0.04, 0.006, 0.002],
            [0.006, 0.09, 0.004],
            [0.002, 0.004, 0.01],
        ])

    @pytest.fixture()
    def market_weights(self):
        return np.array([0.5, 0.3, 0.2])

    def test_no_views_returns_prior(self, sample_cov, market_weights):
        bl = BlackLittermanIC()
        result = bl.optimize(sample_cov, market_weights, views=[])
        assert isinstance(result, BLResult)
        assert len(result.posterior_returns) == 3
        assert len(result.weights) == 3
        assert abs(result.weights.sum() - 1.0) < 0.01

    def test_single_view_shifts_weights(self, sample_cov, market_weights):
        bl = BlackLittermanIC(tau=0.05)
        views = [BLView(asset_index=0, expected_return=0.10, confidence=2.0)]
        result = bl.optimize(sample_cov, market_weights, views)
        prior_w = result.prior_weights
        assert result.weights[0] > prior_w[0], "Positive view should increase weight"

    def test_negative_view_reduces_weight(self, sample_cov, market_weights):
        bl = BlackLittermanIC(tau=0.05)
        views = [BLView(asset_index=1, expected_return=-0.10, confidence=3.0)]
        result = bl.optimize(sample_cov, market_weights, views)
        assert result.weights[1] < result.prior_weights[1]

    def test_weights_sum_to_one(self, sample_cov, market_weights):
        bl = BlackLittermanIC()
        views = [
            BLView(asset_index=0, expected_return=0.08, confidence=1.5),
            BLView(asset_index=2, expected_return=0.05, confidence=1.0),
        ]
        result = bl.optimize(sample_cov, market_weights, views)
        assert abs(result.weights.sum() - 1.0) < 0.01

    def test_view_deltas_populated(self, sample_cov, market_weights):
        bl = BlackLittermanIC(tau=0.05)
        views = [BLView(asset_index=0, expected_return=0.15, confidence=2.0)]
        result = bl.optimize(sample_cov, market_weights, views)
        assert 0 in result.view_deltas
        assert result.view_deltas[0] != 0.0

    def test_optimize_with_ic(self, sample_cov, market_weights):
        bl = BlackLittermanIC()
        factor_ics = {0: 0.05, 1: -0.02, 2: 0.08}
        factor_returns = {0: 0.10, 1: -0.05, 2: 0.12}
        result = bl.optimize_with_ic(sample_cov, market_weights, factor_ics, factor_returns)
        assert isinstance(result, BLResult)
        assert len(result.weights) == 3

    def test_optimize_with_ic_filters_weak(self, sample_cov, market_weights):
        bl = BlackLittermanIC()
        factor_ics = {0: 0.001, 1: 0.002}
        factor_returns = {0: 0.10, 1: 0.05}
        result = bl.optimize_with_ic(sample_cov, market_weights, factor_ics, factor_returns)
        assert isinstance(result, BLResult)

    def test_empty_cov(self):
        bl = BlackLittermanIC()
        result = bl.optimize(np.array([]), np.array([]), [])
        assert len(result.weights) == 0

    def test_high_confidence_view_dominates(self, sample_cov, market_weights):
        bl = BlackLittermanIC(tau=0.05)
        low_conf = bl.optimize(sample_cov, market_weights, [
            BLView(asset_index=0, expected_return=0.10, confidence=0.5),
        ])
        high_conf = bl.optimize(sample_cov, market_weights, [
            BLView(asset_index=0, expected_return=0.10, confidence=10.0),
        ])
        assert abs(high_conf.view_deltas.get(0, 0)) >= abs(low_conf.view_deltas.get(0, 0))
