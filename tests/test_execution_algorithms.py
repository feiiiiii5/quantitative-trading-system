from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from core.execution_algorithms import (
    DarkPoolRouter,
    FillResult,
    ISAlgorithm,
    MarketState,
    OrderSlice,
    POVAlgorithm,
    SmartOrderRouter,
    TWAPAlgorithm,
    VWAPAlgorithm,
)

_START = datetime(2024, 1, 15, 9, 30, 0)
_END = datetime(2024, 1, 15, 15, 0, 0)


def _make_market_state(
    current_price: float = 100.0,
    current_volume: float = 50000.0,
    vwap: float = 100.5,
    time_in_session_pct: float = 0.5,
    adv_20d: float = 1_000_000.0,
    bid_ask_spread: float = 0.05,
) -> MarketState:
    return MarketState(
        current_price=current_price,
        current_volume=current_volume,
        vwap=vwap,
        time_in_session_pct=time_in_session_pct,
        adv_20d=adv_20d,
        bid_ask_spread=bid_ask_spread,
    )


class TestMarketState:
    def test_market_state_creation(self) -> None:
        ms = _make_market_state()
        assert ms.current_price == 100.0
        assert ms.current_volume == 50000.0
        assert ms.vwap == 100.5
        assert ms.time_in_session_pct == 0.5
        assert ms.adv_20d == 1_000_000.0
        assert ms.bid_ask_spread == 0.05


class TestOrderSlice:
    def test_order_slice_defaults(self) -> None:
        os = OrderSlice(quantity=100)
        assert os.quantity == 100
        assert os.limit_price is None
        assert os.time_offset_seconds == 0.0
        assert os.algorithm_name == ""


class TestFillResult:
    def test_fill_result_fields(self) -> None:
        fr = FillResult(filled_quantity=50, fill_price=99.95, venue="dark_pool", savings_bps=2.5)
        assert fr.filled_quantity == 50
        assert fr.fill_price == 99.95
        assert fr.venue == "dark_pool"
        assert fr.savings_bps == 2.5


class TestTWAPAlgorithm:
    def test_twap_validates_total_qty(self) -> None:
        with pytest.raises(ValueError, match="total_qty must be positive"):
            TWAPAlgorithm(total_qty=0, start_time=_START, end_time=_END)
        with pytest.raises(ValueError, match="total_qty must be positive"):
            TWAPAlgorithm(total_qty=-10, start_time=_START, end_time=_END)

    def test_twap_validates_n_slices(self) -> None:
        with pytest.raises(ValueError, match="n_slices must be positive"):
            TWAPAlgorithm(total_qty=100, start_time=_START, end_time=_END, n_slices=0)
        with pytest.raises(ValueError, match="n_slices must be positive"):
            TWAPAlgorithm(total_qty=100, start_time=_START, end_time=_END, n_slices=-1)

    def test_twap_validates_time_range(self) -> None:
        with pytest.raises(ValueError, match="end_time must be after start_time"):
            TWAPAlgorithm(total_qty=100, start_time=_END, end_time=_START)
        with pytest.raises(ValueError, match="end_time must be after start_time"):
            TWAPAlgorithm(total_qty=100, start_time=_START, end_time=_START)

    def test_twap_slices_sum_to_total(self) -> None:
        total = 1003
        algo = TWAPAlgorithm(total_qty=total, start_time=_START, end_time=_END, n_slices=10)
        filled = 0
        t = _END + timedelta(days=1)
        ms = _make_market_state()
        for _ in range(20):
            if algo.is_complete():
                break
            sl = algo.next_slice(t, ms)
            if sl is not None:
                filled += sl.quantity
        assert filled == total

    def test_twap_returns_none_before_schedule(self) -> None:
        algo = TWAPAlgorithm(total_qty=100, start_time=_START, end_time=_END, n_slices=10)
        ms = _make_market_state()
        result = algo.next_slice(_START - timedelta(hours=1), ms)
        assert result is None

    def test_twap_returns_slice_at_schedule(self) -> None:
        algo = TWAPAlgorithm(total_qty=100, start_time=_START, end_time=_END, n_slices=10)
        ms = _make_market_state()
        result = algo.next_slice(_END + timedelta(hours=1), ms)
        assert isinstance(result, OrderSlice)
        assert result.quantity > 0

    def test_twap_is_complete_after_all_filled(self) -> None:
        algo = TWAPAlgorithm(total_qty=10, start_time=_START, end_time=_END, n_slices=2)
        ms = _make_market_state()
        t = _END + timedelta(hours=1)
        while not algo.is_complete():
            algo.next_slice(t, ms)
        assert algo.is_complete()

    def test_twap_algorithm_name(self) -> None:
        algo = TWAPAlgorithm(total_qty=100, start_time=_START, end_time=_END, n_slices=10)
        ms = _make_market_state()
        sl = algo.next_slice(_END + timedelta(hours=1), ms)
        assert sl is not None
        assert sl.algorithm_name == "TWAP"


class TestVWAPAlgorithm:
    def test_vwap_validates_total_qty(self) -> None:
        with pytest.raises(ValueError, match="total_qty must be positive"):
            VWAPAlgorithm(total_qty=0, volume_profile={}, start_time=_START, end_time=_END)

    def test_vwap_slices_sum_to_total(self) -> None:
        total = 997
        profile = {"b0": 0.1, "b1": 0.15, "b2": 0.2, "b3": 0.15, "b4": 0.1,
                   "b5": 0.05, "b6": 0.05, "b7": 0.05, "b8": 0.05, "b9": 0.1}
        algo = VWAPAlgorithm(total_qty=total, volume_profile=profile, start_time=_START, end_time=_END, n_slices=10)
        assert sum(algo._slice_quantities) == total

    def test_vwap_empty_volume_profile(self) -> None:
        algo = VWAPAlgorithm(total_qty=100, volume_profile={}, start_time=_START, end_time=_END, n_slices=10)
        ms = _make_market_state()
        sl = algo.next_slice(_END + timedelta(hours=1), ms)
        assert sl is not None
        assert sl.quantity > 0

    def test_vwap_algorithm_name(self) -> None:
        algo = VWAPAlgorithm(total_qty=100, volume_profile={}, start_time=_START, end_time=_END, n_slices=10)
        ms = _make_market_state()
        sl = algo.next_slice(_END + timedelta(hours=1), ms)
        assert sl is not None
        assert sl.algorithm_name == "VWAP"


class TestPOVAlgorithm:
    def test_pov_validates_total_qty(self) -> None:
        with pytest.raises(ValueError, match="total_qty must be positive"):
            POVAlgorithm(total_qty=0)
        with pytest.raises(ValueError, match="total_qty must be positive"):
            POVAlgorithm(total_qty=-5)

    def test_pov_validates_participation_rate(self) -> None:
        with pytest.raises(ValueError, match="participation_rate must be in"):
            POVAlgorithm(total_qty=100, participation_rate=0.0)
        with pytest.raises(ValueError, match="participation_rate must be in"):
            POVAlgorithm(total_qty=100, participation_rate=1.0)
        with pytest.raises(ValueError, match="participation_rate must be in"):
            POVAlgorithm(total_qty=100, participation_rate=-0.1)

    def test_pov_returns_none_zero_volume(self) -> None:
        algo = POVAlgorithm(total_qty=100, participation_rate=0.05)
        ms = _make_market_state(current_volume=0)
        result = algo.next_slice(_START, ms)
        assert result is None

    def test_pov_slice_quantity(self) -> None:
        rate = 0.05
        volume = 10000.0
        algo = POVAlgorithm(total_qty=10000, participation_rate=rate)
        ms = _make_market_state(current_volume=volume)
        sl = algo.next_slice(_START, ms)
        assert sl is not None
        expected = max(1, int(volume * rate))
        assert sl.quantity == expected

    def test_pov_is_complete_after_all_filled(self) -> None:
        algo = POVAlgorithm(total_qty=5, participation_rate=0.05)
        ms = _make_market_state(current_volume=100000.0)
        t = _START
        for _ in range(100):
            if algo.is_complete():
                break
            sl = algo.next_slice(t, ms)
            t += timedelta(seconds=1)
            ms = _make_market_state(current_volume=100000.0 + _ * 100)
        assert algo.is_complete()


class TestISAlgorithm:
    def test_is_validates_total_qty(self) -> None:
        with pytest.raises(ValueError, match="total_qty must be positive"):
            ISAlgorithm(total_qty=0, risk_aversion=1.0, volatility=0.02, time_horizon=3600)

    def test_is_validates_risk_aversion(self) -> None:
        with pytest.raises(ValueError, match="risk_aversion must be non-negative"):
            ISAlgorithm(total_qty=100, risk_aversion=-0.5, volatility=0.02, time_horizon=3600)

    def test_is_validates_volatility(self) -> None:
        with pytest.raises(ValueError, match="volatility must be non-negative"):
            ISAlgorithm(total_qty=100, risk_aversion=1.0, volatility=-0.01, time_horizon=3600)

    def test_is_validates_time_horizon(self) -> None:
        with pytest.raises(ValueError, match="time_horizon must be positive"):
            ISAlgorithm(total_qty=100, risk_aversion=1.0, volatility=0.02, time_horizon=0)
        with pytest.raises(ValueError, match="time_horizon must be positive"):
            ISAlgorithm(total_qty=100, risk_aversion=1.0, volatility=0.02, time_horizon=-100)

    def test_is_trajectory_uniform_zero_kappa(self) -> None:
        algo = ISAlgorithm(total_qty=100, risk_aversion=0.0, volatility=0.0, time_horizon=3600, n_slices=10)
        traj = algo.compute_optimal_trajectory()
        expected = 1.0 / 10
        for f in traj:
            assert abs(f - expected) < 1e-10

    def test_is_trajectory_front_loaded_high_kappa(self) -> None:
        algo = ISAlgorithm(total_qty=100, risk_aversion=1.0, volatility=0.3, time_horizon=100, n_slices=10)
        traj = algo.compute_optimal_trajectory()
        assert traj[0] > traj[-1]

    def test_is_returns_limit_price(self) -> None:
        algo = ISAlgorithm(
            total_qty=100, risk_aversion=1.0, volatility=0.02, time_horizon=3600,
            n_slices=2, start_time=_START, end_time=_END,
        )
        ms = _make_market_state(current_price=105.25)
        sl = algo.next_slice(_END + timedelta(hours=1), ms)
        assert sl is not None
        assert sl.limit_price == 105.25

    def test_is_algorithm_name(self) -> None:
        algo = ISAlgorithm(
            total_qty=100, risk_aversion=1.0, volatility=0.02, time_horizon=3600,
            n_slices=2, start_time=_START, end_time=_END,
        )
        ms = _make_market_state()
        sl = algo.next_slice(_END + timedelta(hours=1), ms)
        assert sl is not None
        assert sl.algorithm_name == "IS"


class TestDarkPoolRouter:
    def test_dark_pool_validates_internal_match_rate(self) -> None:
        with pytest.raises(ValueError, match="internal_match_rate must be in"):
            DarkPoolRouter(internal_match_rate=-0.1)
        with pytest.raises(ValueError, match="internal_match_rate must be in"):
            DarkPoolRouter(internal_match_rate=1.5)

    def test_dark_pool_validates_max_match_pct(self) -> None:
        with pytest.raises(ValueError, match="max_match_pct must be in"):
            DarkPoolRouter(max_match_pct=0.0)
        with pytest.raises(ValueError, match="max_match_pct must be in"):
            DarkPoolRouter(max_match_pct=1.5)

    def test_dark_pool_try_match_returns_fillresult_or_none(self) -> None:
        dp = DarkPoolRouter(internal_match_rate=0.5, max_match_pct=0.8)
        order = OrderSlice(quantity=100)
        ms = _make_market_state()
        results: list[FillResult | None] = []
        for _ in range(200):
            dp_fresh = DarkPoolRouter(internal_match_rate=0.5, max_match_pct=0.8)
            results.append(dp_fresh.try_internal_match(order, ms))
        types = {type(r) for r in results}
        assert FillResult in types or type(None) in types

    def test_dark_pool_match_rate_initial(self) -> None:
        dp = DarkPoolRouter()
        assert dp.match_rate == 0.0

    def test_dark_pool_zero_quantity_returns_none(self) -> None:
        dp = DarkPoolRouter()
        order = OrderSlice(quantity=0)
        result = dp.try_internal_match(order, _make_market_state())
        assert result is None


class TestSmartOrderRouter:
    def test_smart_router_validates_total_qty(self) -> None:
        router = SmartOrderRouter()
        with pytest.raises(ValueError, match="total_qty must be positive"):
            router.route_order(total_qty=0, symbol="AAPL", adv_20d=1_000_000)

    def test_smart_router_validates_urgency(self) -> None:
        router = SmartOrderRouter()
        with pytest.raises(ValueError, match="urgency must be in"):
            router.route_order(total_qty=100, symbol="AAPL", adv_20d=1_000_000, urgency=-0.1)
        with pytest.raises(ValueError, match="urgency must be in"):
            router.route_order(total_qty=100, symbol="AAPL", adv_20d=1_000_000, urgency=1.5)

    def test_smart_router_small_order_twap(self) -> None:
        router = SmartOrderRouter()
        adv = 1_000_000
        small_qty = int(adv * 0.005)
        algo = router.route_order(total_qty=small_qty, symbol="AAPL", adv_20d=adv, start_time=_START, end_time=_END)
        assert isinstance(algo, TWAPAlgorithm)

    def test_smart_router_medium_order_vwap(self) -> None:
        router = SmartOrderRouter()
        adv = 1_000_000
        medium_qty = int(adv * 0.03)
        algo = router.route_order(total_qty=medium_qty, symbol="AAPL", adv_20d=adv, start_time=_START, end_time=_END)
        assert isinstance(algo, VWAPAlgorithm)

    def test_smart_router_large_order_high_urgency_is(self) -> None:
        router = SmartOrderRouter()
        adv = 1_000_000
        large_qty = int(adv * 0.07)
        algo = router.route_order(
            total_qty=large_qty, symbol="AAPL", adv_20d=adv,
            urgency=0.8, start_time=_START, end_time=_END,
        )
        assert isinstance(algo, ISAlgorithm)

    def test_smart_router_large_order_low_urgency_pov(self) -> None:
        router = SmartOrderRouter()
        adv = 1_000_000
        large_qty = int(adv * 0.07)
        algo = router.route_order(
            total_qty=large_qty, symbol="AAPL", adv_20d=adv,
            urgency=0.3, start_time=_START, end_time=_END,
        )
        assert isinstance(algo, POVAlgorithm)

    def test_smart_router_very_large_order_is(self) -> None:
        router = SmartOrderRouter()
        adv = 1_000_000
        very_large_qty = int(adv * 0.15)
        algo = router.route_order(
            total_qty=very_large_qty, symbol="AAPL", adv_20d=adv,
            start_time=_START, end_time=_END,
        )
        assert isinstance(algo, ISAlgorithm)

    def test_smart_router_zero_adv_twap(self) -> None:
        router = SmartOrderRouter()
        algo = router.route_order(total_qty=100, symbol="AAPL", adv_20d=0, start_time=_START, end_time=_END)
        assert isinstance(algo, TWAPAlgorithm)

    def test_smart_router_dark_pool_property(self) -> None:
        router = SmartOrderRouter()
        assert isinstance(router.dark_pool, DarkPoolRouter)
