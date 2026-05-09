import numpy as np
import pandas as pd
import pytest

from core.risk_parity_portfolio import (
    RiskParityPortfolio,
    PortfolioState,
    ICWeightedRiskParity,
)


class TestPortfolioState:

    def test_default_values(self):
        state = PortfolioState()
        assert state.weights == {}
        assert state.risk_contributions == {}
        assert state.portfolio_volatility == 0.0
        assert state.rebalance_needed is False


class TestRiskParityPortfolio:

    def test_insufficient_data_returns_equal_weight(self):
        portfolio = RiskParityPortfolio(symbols=["A", "B", "C"])
        state = portfolio.compute_target_weights()
        assert len(state.weights) == 3
        for w in state.weights.values():
            assert abs(w - 1.0 / 3) < 0.01

    def test_update_returns_and_compute(self):
        portfolio = RiskParityPortfolio(symbols=["A", "B", "C"])
        rng = np.random.default_rng(42)
        for _ in range(30):
            returns = rng.normal(0.001, 0.02, 3)
            portfolio.update_returns(returns)
        state = portfolio.compute_target_weights()
        assert len(state.weights) == 3
        total = sum(state.weights.values())
        assert abs(total - 1.0) < 0.05

    def test_update_ic_adjusts_weights(self):
        portfolio = RiskParityPortfolio(symbols=["A", "B", "C"])
        rng = np.random.default_rng(42)
        for _ in range(30):
            returns = rng.normal(0.001, 0.02, 3)
            portfolio.update_returns(returns)

        for _ in range(25):
            portfolio.update_ic("A", 0.8, 0.02)
            portfolio.update_ic("B", 0.1, 0.001)
            portfolio.update_ic("C", 0.5, 0.01)

        state = portfolio.compute_target_weights()
        assert "A" in state.ic_adjustments
        assert "B" in state.ic_adjustments

    def test_wrong_returns_length_ignored(self):
        portfolio = RiskParityPortfolio(symbols=["A", "B"])
        portfolio.update_returns(np.array([0.01, 0.02, 0.03]))
        state = portfolio.compute_target_weights()
        assert abs(state.weights.get("A", 0) - 0.5) < 0.01

    def test_apply_rebalance_first_time(self):
        portfolio = RiskParityPortfolio(symbols=["A", "B"])
        target = PortfolioState(weights={"A": 0.6, "B": 0.4})
        result = portfolio.apply_rebalance(target)
        assert result == {"A": 0.6, "B": 0.4}
        assert portfolio.current_weights == {"A": 0.6, "B": 0.4}

    def test_apply_rebalance_with_drift(self):
        portfolio = RiskParityPortfolio(symbols=["A", "B"])
        portfolio.apply_rebalance(PortfolioState(weights={"A": 0.5, "B": 0.5}))
        target = PortfolioState(weights={"A": 0.7, "B": 0.3})
        result = portfolio.apply_rebalance(target)
        total = sum(result.values())
        assert abs(total - 1.0) < 0.05

    def test_apply_rebalance_turnover_cap(self):
        portfolio = RiskParityPortfolio(
            symbols=["A", "B", "C"],
            turnover_cap=0.10,
        )
        portfolio.apply_rebalance(PortfolioState(weights={"A": 0.33, "B": 0.33, "C": 0.34}))
        target = PortfolioState(weights={"A": 0.8, "B": 0.1, "C": 0.1})
        result = portfolio.apply_rebalance(target)
        total = sum(result.values())
        assert abs(total - 1.0) < 0.05

    def test_factor_summary(self):
        portfolio = RiskParityPortfolio(symbols=["A", "B"])
        portfolio.update_ic("A", 0.5, 0.01)
        summary = portfolio.factor_summary
        assert isinstance(summary, dict)


class TestICWeightedRiskParity:

    def test_empty_cov(self):
        ic_rp = ICWeightedRiskParity()
        w = ic_rp.compute_weights(np.array([]).reshape(0, 0), np.array([]))
        assert len(w) == 0

    def test_equal_ic_equal_weights(self):
        ic_rp = ICWeightedRiskParity()
        rng = np.random.default_rng(42)
        n = 4
        cov = np.cov(rng.normal(0, 0.02, (100, n)).T)
        ics = np.array([0.05, 0.05, 0.05, 0.05])
        w = ic_rp.compute_weights(cov, ics)
        assert len(w) == n
        assert abs(w.sum() - 1.0) < 0.05

    def test_higher_ic_gets_more_weight(self):
        ic_rp = ICWeightedRiskParity()
        rng = np.random.default_rng(42)
        n = 3
        cov = np.cov(rng.normal(0, 0.02, (100, n)).T)
        ics = np.array([0.10, 0.02, 0.05])
        w = ic_rp.compute_weights(cov, ics)
        assert w[0] > w[1]

    def test_zero_ic_gets_min_weight(self):
        ic_rp = ICWeightedRiskParity(min_ic_weight=0.3)
        rng = np.random.default_rng(42)
        n = 3
        cov = np.cov(rng.normal(0, 0.02, (100, n)).T)
        ics = np.array([0.0, 0.0, 0.0])
        w = ic_rp.compute_weights(cov, ics)
        assert all(wi > 0 for wi in w)

    def test_mismatched_ic_length(self):
        ic_rp = ICWeightedRiskParity()
        cov = np.eye(3)
        ics = np.array([0.05, 0.05])
        w = ic_rp.compute_weights(cov, ics)
        assert len(w) == 3
        assert abs(w.sum() - 1.0) < 0.01

    def test_compute_risk_contributions(self):
        ic_rp = ICWeightedRiskParity()
        rng = np.random.default_rng(42)
        n = 3
        cov = np.cov(rng.normal(0, 0.02, (100, n)).T)
        w = np.array([0.4, 0.3, 0.3])
        rc = ic_rp.compute_risk_contributions(w, cov)
        assert len(rc) == n
        assert all(np.isfinite(rc))

    def test_compute_risk_contributions_empty(self):
        ic_rp = ICWeightedRiskParity()
        rc = ic_rp.compute_risk_contributions(np.array([]), np.array([]).reshape(0, 0))
        assert len(rc) == 0
