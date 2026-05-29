from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


class TestRegimeDetectAPI:
    def test_detect_regime_hmm_basic(self):
        from core.volatility import detect_regime_hmm

        rng = np.random.default_rng(42)
        returns = np.concatenate([
            rng.normal(-0.002, 0.03, 100),
            rng.normal(0.001, 0.01, 100),
            rng.normal(0.003, 0.02, 100),
        ])
        result = detect_regime_hmm(returns, n_states=3)
        assert "error" not in result
        assert "current_label" in result
        assert result["current_label"] in ("BEAR", "NEUTRAL", "BULL")
        assert len(result["states"]) == 3
        assert len(result["transition_matrix"]) == 3

    def test_detect_regime_hmm_insufficient_data(self):
        from core.volatility import detect_regime_hmm

        result = detect_regime_hmm(np.array([0.01] * 30), n_states=3)
        assert "error" in result

    def test_detect_regime_hmm_two_states(self):
        from core.volatility import detect_regime_hmm

        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.02, 120)
        result = detect_regime_hmm(returns, n_states=2)
        assert "error" not in result
        assert len(result["states"]) == 2
        for state in result["states"]:
            assert state["label"] in ("BEAR", "BULL", "NEUTRAL")


class TestGarchVolatilityAPI:
    def test_fit_garch_basic(self):
        from core.volatility import fit_garch

        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.02, 252)
        result = fit_garch(returns)
        assert "error" not in result
        assert result["current_volatility"] > 0
        assert result["long_run_volatility"] > 0
        assert 0 < result["persistence"] < 1
        assert result["forecast_5d"] is not None

    def test_fit_garch_insufficient_data(self):
        from core.volatility import fit_garch

        result = fit_garch(np.array([0.01] * 20))
        assert "error" in result

    def test_fit_garch_regime_label(self):
        from core.volatility import fit_garch

        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.02, 252)
        result = fit_garch(returns)
        assert result["regime"] in ("HIGH_VOL", "LOW_VOL", "NORMAL")


class TestPairMiningAPI:
    def test_engle_granger_cointegrated(self):
        from core.statistical_arbitrage import engle_granger_test

        rng = np.random.default_rng(42)
        n = 200
        x = np.cumsum(rng.normal(0, 1, n))
        y = 2.0 * x + rng.normal(0, 0.5, n)
        result = engle_granger_test(
            pd.Series(y, name="Y"),
            pd.Series(x, name="X"),
        )
        assert result.is_cointegrated
        assert abs(result.hedge_ratio - 2.0) < 0.5
        assert result.half_life < 30

    def test_engle_granger_not_cointegrated(self):
        from core.statistical_arbitrage import engle_granger_test

        rng = np.random.default_rng(99)
        n = 200
        x = np.cumsum(rng.normal(0, 1, n)) + np.cumsum(rng.normal(0, 0.5, n))
        y = np.cumsum(rng.normal(0, 1, n)) + np.cumsum(rng.normal(0, 0.5, n))
        result = engle_granger_test(
            pd.Series(y, name="Y"),
            pd.Series(x, name="X"),
            significance=0.01,
        )
        assert isinstance(result.is_cointegrated, bool)

    def test_pair_mining_engine(self):
        from core.statistical_arbitrage import PairMiningEngine

        rng = np.random.default_rng(42)
        n = 200
        base = np.cumsum(rng.normal(0, 1, n))
        prices_df = pd.DataFrame({
            "A": base + 100,
            "B": 1.5 * base + 50 + rng.normal(0, 0.3, n),
            "C": np.cumsum(rng.normal(0, 1, n)) + 100,
        })
        engine = PairMiningEngine(pvalue_threshold=0.10)
        results = engine.find_cointegrated_pairs(prices_df, ["A", "B", "C"])
        assert isinstance(results, list)


class TestRiskParityOptimizeAPI:
    def test_risk_parity_portfolio_basic(self):
        from core.risk_parity_portfolio import RiskParityPortfolio

        symbols = ["A", "B", "C"]
        rp = RiskParityPortfolio(symbols=symbols)
        rng = np.random.default_rng(42)
        for _ in range(60):
            returns = rng.normal(0, 0.02, 3)
            rp.update_returns(returns)

        state = rp.compute_target_weights()
        assert len(state.weights) == 3
        assert abs(sum(state.weights.values()) - 1.0) < 0.05
        assert state.portfolio_volatility > 0

    def test_risk_parity_insufficient_data(self):
        from core.risk_parity_portfolio import RiskParityPortfolio

        symbols = ["A", "B"]
        rp = RiskParityPortfolio(symbols=symbols)
        state = rp.compute_target_weights()
        assert abs(state.weights["A"] - 0.5) < 0.01
        assert abs(state.weights["B"] - 0.5) < 0.01


class TestPortfolioAnalyticsRequest:
    def test_request_model_defaults(self):
        from api.routers.models import PortfolioAnalyticsRequest

        req = PortfolioAnalyticsRequest(symbols="600519,000858")
        assert req.period == "1y"
        assert req.n_simulations == 5000
        assert req.include_factor_attribution is True
        assert req.include_regime is True
        assert req.include_var is True
        assert req.include_risk_parity is True

    def test_request_model_custom(self):
        from api.routers.models import PortfolioAnalyticsRequest

        req = PortfolioAnalyticsRequest(
            symbols="600519,000858,300750",
            period="3m",
            n_simulations=10000,
            include_factor_attribution=False,
        )
        assert req.n_simulations == 10000
        assert req.include_factor_attribution is False
        assert req.include_regime is True


class TestRegimeDetectRequest:
    def test_request_model_defaults(self):
        from api.routers.models import RegimeDetectRequest

        req = RegimeDetectRequest(symbol="600519")
        assert req.period == "1y"
        assert req.n_states == 3

    def test_request_model_n_states_validation(self):
        from api.routers.models import RegimeDetectRequest

        with pytest.raises(ValueError):
            RegimeDetectRequest(symbol="600519", n_states=1)
        with pytest.raises(ValueError):
            RegimeDetectRequest(symbol="600519", n_states=7)


class TestGarchVolatilityRequest:
    def test_request_model_defaults(self):
        from api.routers.models import GarchVolatilityRequest

        req = GarchVolatilityRequest(symbol="600519")
        assert req.period == "1y"
        assert req.iterations == 5

    def test_request_model_iterations_validation(self):
        from api.routers.models import GarchVolatilityRequest

        with pytest.raises(ValueError):
            GarchVolatilityRequest(symbol="600519", iterations=0)


class TestRiskParityOptimizeRequest:
    def test_request_model_defaults(self):
        from api.routers.models import RiskParityOptimizeRequest

        req = RiskParityOptimizeRequest(symbols="600519,000858")
        assert req.period == "1y"
        assert req.drift_threshold == 0.05
        assert req.turnover_cap == 0.30
