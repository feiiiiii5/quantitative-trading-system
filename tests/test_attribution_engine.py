import numpy as np
import pandas as pd
import pytest

from core.attribution_engine import (
    AttributionContext,
    AttributionEngine,
    AttributionReport,
    BrinsonResult,
    FactorAttributionResult,
    RegimeAttributionResult,
    TradeAttributionResult,
    brinson_attribution,
    factor_attribution,
    regime_attribution,
    trade_attribution,
    generate_monthly_report,
)


class TestBrinsonAttribution:
    def test_empty_inputs_returns_default(self):
        result = brinson_attribution({}, {}, {}, {})
        assert result.total_excess == 0.0
        assert result.allocation_effect == 0.0
        assert result.selection_effect == 0.0
        assert result.interaction_effect == 0.0

    def test_equal_weights_zero_excess(self):
        weights = {"tech": 0.5, "finance": 0.5}
        bench = {"tech": 0.5, "finance": 0.5}
        asset_rets = {"tech:main": 0.1, "finance:main": 0.05}
        cat_rets = {"tech": 0.1, "finance": 0.05}
        result = brinson_attribution(weights, bench, asset_rets, cat_rets)
        assert abs(result.allocation_effect) < 1e-6
        assert abs(result.selection_effect) < 1e-6
        assert abs(result.total_excess) < 1e-6

    def test_overweight_positive_category(self):
        pw = {"tech": 0.7, "finance": 0.3}
        bw = {"tech": 0.5, "finance": 0.5}
        asset_rets = {"tech:main": 0.1, "finance:main": 0.02}
        cat_rets = {"tech": 0.1, "finance": 0.02}
        result = brinson_attribution(pw, bw, asset_rets, cat_rets)
        assert result.allocation_effect > 0
        assert result.total_excess > 0

    def test_category_breakdown_populated(self):
        pw = {"tech": 0.6}
        bw = {"tech": 0.4}
        asset_rets = {"tech:main": 0.08}
        cat_rets = {"tech": 0.08}
        result = brinson_attribution(pw, bw, asset_rets, cat_rets)
        assert "tech" in result.category_breakdown
        bd = result.category_breakdown["tech"]
        assert "allocation" in bd
        assert "selection" in bd
        assert "interaction" in bd

    def test_missing_category_in_benchmark(self):
        pw = {"tech": 1.0}
        bw = {"finance": 1.0}
        asset_rets = {"tech:main": 0.1}
        cat_rets = {"tech": 0.1, "finance": 0.05}
        result = brinson_attribution(pw, bw, asset_rets, cat_rets)
        assert result.total_excess != 0.0


class TestFactorAttribution:
    def test_empty_returns_default(self):
        result = factor_attribution(pd.Series(dtype=float), pd.DataFrame(), pd.Series(dtype=float))
        assert result.total_return == 0.0
        assert result.r_squared == 0.0

    def test_insufficient_common_index(self):
        idx = pd.date_range("2024-01-01", periods=3)
        pr = pd.Series([0.01, 0.02, 0.03], index=idx)
        fe = pd.DataFrame({"mkt": [1.0, 1.0, 1.0]}, index=idx)
        fr = pd.Series([0.005, 0.005, 0.005], index=idx)
        result = factor_attribution(pr, fe, fr)
        assert result.total_return == 0.0

    def test_dimension_mismatch_returns_total_return_only(self):
        np.random.seed(42)
        n = 60
        idx = pd.date_range("2024-01-01", periods=n)
        factor_ret = pd.Series(np.random.normal(0.001, 0.01, n), index=idx)
        exposure = pd.DataFrame({"mkt": np.ones(n)}, index=idx)
        port_ret = factor_ret * 1.0 + np.random.normal(0, 0.001, n)
        port_ret = pd.Series(port_ret, index=idx)
        result = factor_attribution(port_ret, exposure, factor_ret)
        assert result.total_return != 0.0
        assert result.factor_contributions == {}
        assert result.r_squared == 0.0

    def test_matching_dimensions(self):
        n_factors = 5
        idx = pd.date_range("2024-01-01", periods=n_factors)
        pr = pd.Series([0.01, 0.02, -0.01, 0.03, 0.005], index=idx)
        fe = pd.DataFrame(
            {f"f{i}": np.random.uniform(0.5, 1.5, n_factors) for i in range(n_factors)},
            index=idx,
        )
        fr = pd.Series([0.005, -0.003, 0.008, -0.001, 0.004], index=idx)
        result = factor_attribution(pr, fe, fr)
        assert result.total_return != 0.0
        assert len(result.factor_contributions) > 0


class TestRegimeAttribution:
    def test_empty_returns_default(self):
        result = regime_attribution(pd.Series(dtype=float), pd.Series(dtype=str))
        assert result.dominant_regime == ""

    def test_insufficient_common_index(self):
        idx = pd.date_range("2024-01-01", periods=3)
        rets = pd.Series([0.01, 0.02, -0.01], index=idx)
        labels = pd.Series(["normal", "high_vol", "normal"], index=idx)
        result = regime_attribution(rets, labels)
        assert result.dominant_regime == ""

    def test_two_regimes(self):
        n = 30
        idx = pd.date_range("2024-01-01", periods=n)
        rets = pd.Series(np.random.normal(0.001, 0.02, n), index=idx)
        labels = pd.Series(["normal"] * 15 + ["high_vol"] * 15, index=idx)
        result = regime_attribution(rets, labels)
        assert len(result.regime_breakdown) == 2
        assert "normal" in result.regime_breakdown
        assert "high_vol" in result.regime_breakdown
        assert result.dominant_regime != ""

    def test_single_regime(self):
        n = 20
        idx = pd.date_range("2024-01-01", periods=n)
        rets = pd.Series(np.random.normal(0.001, 0.01, n), index=idx)
        labels = pd.Series(["normal"] * n, index=idx)
        result = regime_attribution(rets, labels)
        assert len(result.regime_breakdown) == 1
        assert result.dominant_regime == "normal"


class TestTradeAttribution:
    def test_empty_trades(self):
        result = trade_attribution([])
        assert result.total_pnl == 0.0
        assert result.holding_pnl == 0.0

    def test_buy_trade_profit(self):
        trades = [{
            "symbol": "600000",
            "side": "buy",
            "entry_price": 10.0,
            "exit_price": 12.0,
            "quantity": 100,
            "commission": 5.0,
            "slippage": 2.0,
        }]
        result = trade_attribution(trades)
        assert result.total_pnl > 0
        assert result.holding_pnl == pytest.approx(200.0)
        assert result.friction_cost == pytest.approx(7.0)
        assert len(result.trade_breakdown) == 1

    def test_sell_trade_profit(self):
        trades = [{
            "symbol": "600000",
            "side": "sell",
            "entry_price": 12.0,
            "exit_price": 10.0,
            "quantity": 100,
            "commission": 5.0,
            "slippage": 2.0,
        }]
        result = trade_attribution(trades)
        assert result.holding_pnl == pytest.approx(200.0)
        assert result.total_pnl == pytest.approx(193.0)

    def test_multiple_trades(self):
        trades = [
            {"symbol": "A", "side": "buy", "entry_price": 10, "exit_price": 11, "quantity": 100, "commission": 3, "slippage": 1},
            {"symbol": "B", "side": "buy", "entry_price": 20, "exit_price": 18, "quantity": 50, "commission": 3, "slippage": 1},
        ]
        result = trade_attribution(trades)
        assert len(result.trade_breakdown) == 2
        assert result.total_pnl == pytest.approx(100 - 100 - 4 - 4)

    def test_missing_fields_default(self):
        trades = [{"symbol": "X"}]
        result = trade_attribution(trades)
        assert result.total_pnl == 0.0
        assert result.holding_pnl == 0.0


class TestAttributionEngine:
    def test_run_full_with_brinson(self):
        engine = AttributionEngine()
        ctx = AttributionContext(
            portfolio_weights={"tech": 0.6, "finance": 0.4},
            benchmark_weights={"tech": 0.5, "finance": 0.5},
            asset_returns={"tech:main": 0.1, "finance:main": 0.05},
            category_returns={"tech": 0.1, "finance": 0.05},
            date_range=("2024-01-01", "2024-12-31"),
        )
        report = engine.run_full_attribution(ctx)
        assert report.brinson is not None
        assert report.period == "2024-01-01~2024-12-31"
        assert "excess_return" in report.summary

    def test_run_full_with_trades(self):
        engine = AttributionEngine()
        ctx = AttributionContext(
            trades=[{"symbol": "A", "side": "buy", "entry_price": 10, "exit_price": 12, "quantity": 100, "commission": 5, "slippage": 1}],
            date_range=("2024-01-01", "2024-06-30"),
        )
        report = engine.run_full_attribution(ctx)
        assert report.trade is not None
        assert report.trade.total_pnl > 0

    def test_compare_periods(self):
        engine = AttributionEngine()
        report_a = AttributionReport(
            period="2024-H1",
            summary={"sharpe_ratio": 1.0, "excess_return": 0.05},
        )
        report_b = AttributionReport(
            period="2024-H2",
            summary={"sharpe_ratio": 1.5, "excess_return": 0.08},
        )
        comparison = engine.compare_periods(report_a, report_b)
        assert comparison["period_a"] == "2024-H1"
        assert comparison["period_b"] == "2024-H2"
        assert comparison["summary_delta"]["sharpe_ratio"] == pytest.approx(0.5)
        assert comparison["summary_delta"]["excess_return"] == pytest.approx(0.03)

    def test_empty_context(self):
        engine = AttributionEngine()
        ctx = AttributionContext()
        report = engine.run_full_attribution(ctx)
        assert report.brinson is None
        assert report.factor is None
        assert report.regime is None
        assert report.trade is None


class TestGenerateMonthlyReport:
    def test_basic_report(self):
        n = 60
        idx = pd.date_range("2024-01-01", periods=n, freq="B")
        pr = pd.Series(np.random.normal(0.001, 0.02, n), index=idx)
        br = pd.Series(np.random.normal(0.0005, 0.015, n), index=idx)
        report = generate_monthly_report(
            portfolio_returns=pr,
            benchmark_returns=br,
            factor_exposures=None,
            factor_returns=None,
            trades=[],
            date_range=("2024-01-01", "2024-03-31"),
        )
        assert report.period == "2024-01-01~2024-03-31"
        assert "portfolio_cumulative_return" in report.summary

    def test_empty_returns(self):
        report = generate_monthly_report(
            portfolio_returns=pd.Series(dtype=float),
            benchmark_returns=pd.Series(dtype=float),
            factor_exposures=None,
            factor_returns=None,
            trades=[],
            date_range=("", ""),
        )
        assert report.period == ""
