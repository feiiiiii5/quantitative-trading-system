import pytest

from core.regime_weight_tracker import RegimeWeightTracker, compute_regime_weight_series
from core.risk_parity_portfolio import RiskParityPortfolio, PortfolioState
from core.data_bundle_cache import DataBundleCache, CacheEntry
from core.backtest.validation import walk_forward_ic_validation, WalkForwardICResult


class TestDashboardIntegration:
    def test_all_new_modules_importable(self):
        assert RegimeWeightTracker is not None
        assert RiskParityPortfolio is not None
        assert DataBundleCache is not None
        assert walk_forward_ic_validation is not None

    def test_dashboard_route_registered(self):
        from api.routes import router
        route_paths = [r.path for r in router.routes]
        assert "/strategy/dashboard" in route_paths

    def test_regime_tracker_with_portfolio(self):
        strategies = ["momentum", "mean_reversion", "trend_following"]
        tracker = RegimeWeightTracker(strategy_names=strategies)
        portfolio = RiskParityPortfolio(symbols=strategies)

        import numpy as np
        rng = np.random.default_rng(42)
        n = 200
        dates = __import__("pandas").date_range("2023-01-01", periods=n, freq="B")
        close = np.cumsum(rng.normal(0.05, 1.5, n)) + 100
        df = __import__("pandas").DataFrame({
            "date": dates,
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": rng.integers(1000, 10000, n),
        })

        snap = tracker.update(df)
        assert snap.regime is not None
        assert len(snap.strategy_weights) == 3

        for _ in range(30):
            portfolio.update_returns(rng.normal(0.001, 0.02, 3))
        state = portfolio.compute_target_weights()
        assert len(state.weights) == 3
