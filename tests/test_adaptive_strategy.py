import numpy as np
import pandas as pd
import pytest


class TestCVaRCalculation:
    def test_empty_returns_zero(self):
        from core.adaptive_strategy import calc_cvar
        assert calc_cvar(np.array([])) == 0.0

    def test_small_sample_returns_zero(self):
        from core.adaptive_strategy import calc_cvar
        returns = np.array([0.01, -0.02, 0.03])
        assert calc_cvar(returns) == 0.0

    def test_all_positive_returns(self):
        from core.adaptive_strategy import calc_cvar
        returns = np.array([0.01, 0.02, 0.03, 0.04, 0.05] * 5)
        result = calc_cvar(returns)
        assert result > 0

    def test_all_negative_returns(self):
        from core.adaptive_strategy import calc_cvar
        returns = np.array([-0.01, -0.02, -0.03, -0.04, -0.05] * 5)
        result = calc_cvar(returns)
        assert result < 0

    def test_mixed_returns(self):
        from core.adaptive_strategy import calc_cvar
        np.random.seed(42)
        returns = np.random.randn(252) * 0.02
        result = calc_cvar(returns)
        assert result < 0

    def test_cvar_custom_confidence(self):
        from core.adaptive_strategy import calc_cvar
        np.random.seed(42)
        returns = np.random.randn(252) * 0.02
        cvar_95 = calc_cvar(returns, confidence=0.95)
        cvar_99 = calc_cvar(returns, confidence=0.99)
        assert abs(cvar_95) <= abs(cvar_99)

    def test_single_value_edge_case(self):
        from core.adaptive_strategy import calc_cvar
        assert calc_cvar(np.array([-0.05] * 10), confidence=0.95) == -0.05


class TestClassifyMarketRegime:
    def test_insufficient_data_returns_all_consolidation(self):
        from core.adaptive_strategy import classify_market_regime, MarketRegime

        df = pd.DataFrame({
            "close": [100, 101, 102],
            "high": [102, 103, 104],
            "low": [99, 100, 101],
            "volume": [1000, 2000, 1500],
        })
        regimes = classify_market_regime(df, window=20)
        assert len(regimes) == 3
        assert all(r == MarketRegime.LOW_VOLATILITY_CONSOLIDATION for r in regimes)

    def test_returns_list_of_regimes(self):
        from core.adaptive_strategy import classify_market_regime, MarketRegime

        np.random.seed(42)
        n = 300
        returns = np.random.randn(n) * 0.01
        price = 100 * np.exp(np.cumsum(returns))
        df = pd.DataFrame({
            "close": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "volume": np.random.randint(1000, 10000, n).astype(float),
        })
        regimes = classify_market_regime(df, window=20)
        assert len(regimes) == n
        valid_regimes = set(MarketRegime)
        for r in regimes:
            assert r in valid_regimes

    def test_missing_volume_column_works(self):
        from core.adaptive_strategy import classify_market_regime, MarketRegime

        np.random.seed(42)
        n = 300
        returns = np.random.randn(n) * 0.01
        price = 100 * np.exp(np.cumsum(returns))
        df = pd.DataFrame({
            "close": price,
            "high": price * 1.01,
            "low": price * 0.99,
        })
        regimes = classify_market_regime(df, window=20)
        assert len(regimes) == n


class TestQLearningWeightAdapter:
    def test_initialization(self):
        from core.adaptive_strategy import QLearningWeightAdapter

        adapter = QLearningWeightAdapter(n_strategies=3)
        assert adapter._n == 3

    def test_select_weights_returns_correct_len(self):
        from core.adaptive_strategy import QLearningWeightAdapter, MarketRegime

        adapter = QLearningWeightAdapter(n_strategies=3)
        base_weights = [0.4, 0.3, 0.3]
        weights = adapter.select_weights(
            MarketRegime.MILD_TREND_UP, 0.2, 0.02, base_weights)
        assert len(weights) == 3

    def test_update_does_not_crash(self):
        from core.adaptive_strategy import QLearningWeightAdapter, MarketRegime

        adapter = QLearningWeightAdapter(n_strategies=3)
        adapter.update(MarketRegime.LOW_VOLATILITY_CONSOLIDATION, 0.1, 0.0, 0, 0.05)

    def test_weights_clipped_between_005_and_060(self):
        from core.adaptive_strategy import QLearningWeightAdapter, MarketRegime

        adapter = QLearningWeightAdapter(n_strategies=3)
        weights = adapter.select_weights(
            MarketRegime.HIGH_VOLATILITY_RANGE, 0.5, -0.03, [0.5, 0.3, 0.2])
        for w in weights:
            assert 0.05 <= w <= 0.60

    def test_weights_sum_to_one(self):
        from core.adaptive_strategy import QLearningWeightAdapter, MarketRegime

        adapter = QLearningWeightAdapter(n_strategies=5)
        weights = adapter.select_weights(
            MarketRegime.STRONG_TREND_UP, 0.25, 0.05, [0.2, 0.2, 0.2, 0.2, 0.2])
        assert pytest.approx(sum(weights), abs=0.01) == 1.0

    def test_discretize_state_format(self):
        from core.adaptive_strategy import QLearningWeightAdapter, MarketRegime

        adapter = QLearningWeightAdapter(n_strategies=3)
        state = adapter._discretize_state(MarketRegime.STRONG_TREND_UP, 0.2, 0.02)
        assert "strong_trend_up" in state
        state2 = adapter._discretize_state(MarketRegime.BEAR_TRAP, 0.4, -0.03)
        assert "bear_trap" in state2
