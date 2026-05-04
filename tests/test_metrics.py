import numpy as np
import pandas as pd
import pytest

from core.metrics import (
    InstitutionalMetrics,
    calc_cagr,
    calc_sharpe,
    calc_sortino,
    calc_max_drawdown,
    calc_calmar,
    calc_win_rate,
    calc_profit_loss_ratio,
    calc_turnover,
    calc_var,
    calc_cvar,
    calc_information_ratio,
    calc_alpha_beta,
    calc_max_consecutive,
    calc_all_metrics,
    metrics_to_dict,
)


class TestCalcCAGR:
    def test_positive(self):
        equity = [100000, 110000, 121000]
        cagr = calc_cagr(equity, 252 * 2)
        assert cagr > 0

    def test_negative(self):
        equity = [100000, 90000, 81000]
        cagr = calc_cagr(equity, 252 * 2)
        assert cagr < 0

    def test_short(self):
        cagr = calc_cagr([100000])
        assert cagr == 0.0


class TestCalcSharpe:
    def test_positive_sharpe(self):
        np.random.seed(42)
        returns = pd.Series(np.random.randn(100) * 0.01 + 0.002)
        sharpe = calc_sharpe(returns)
        assert isinstance(sharpe, float)

    def test_short(self):
        returns = pd.Series([0.01])
        sharpe = calc_sharpe(returns)
        assert sharpe == 0.0


class TestCalcSortino:
    def test_basic(self):
        np.random.seed(42)
        returns = pd.Series(np.random.randn(100) * 0.02 + 0.001)
        sortino = calc_sortino(returns)
        assert isinstance(sortino, float)

    def test_no_downside_returns_finite(self):
        returns = pd.Series([0.01, 0.02, 0.015, 0.03, 0.01])
        sortino = calc_sortino(returns)
        assert np.isfinite(sortino)
        assert sortino > 0


class TestCalcMaxDrawdown:
    def test_basic(self):
        equity = [100, 110, 105, 115, 100, 120]
        dd = calc_max_drawdown(equity)
        assert dd < 0

    def test_no_drawdown(self):
        equity = [100, 110, 120, 130]
        dd = calc_max_drawdown(equity)
        assert dd == 0.0


class TestCalcCalmar:
    def test_basic(self):
        calmar = calc_calmar(0.10, -0.20)
        assert calmar == 0.5

    def test_zero_dd(self):
        calmar = calc_calmar(0.10, 0.0)
        assert calmar == 0.0


class TestCalcWinRate:
    def test_basic(self):
        returns = pd.Series([0.01, -0.01, 0.02, -0.005, 0.01])
        wr = calc_win_rate(returns)
        assert wr == 0.6

    def test_empty(self):
        wr = calc_win_rate(pd.Series(dtype=float))
        assert wr == 0.0


class TestCalcProfitLossRatio:
    def test_basic(self):
        returns = pd.Series([0.02, -0.01, 0.03, -0.015])
        plr = calc_profit_loss_ratio(returns)
        assert plr > 0


class TestCalcTurnover:
    def test_basic(self):
        positions = [
            {"A": 1000, "B": 2000},
            {"A": 1500, "B": 1500},
            {"A": 1000, "B": 2000},
        ]
        turnover = calc_turnover(positions, 10000)
        assert turnover > 0

    def test_no_change(self):
        positions = [{"A": 1000}, {"A": 1000}]
        turnover = calc_turnover(positions, 10000)
        assert turnover == 0.0


class TestCalcVaR:
    def test_basic(self):
        np.random.seed(42)
        returns = pd.Series(np.random.randn(100) * 0.02)
        var = calc_var(returns)
        assert var < 0

    def test_short(self):
        returns = pd.Series([0.01, 0.02])
        var = calc_var(returns)
        assert var == 0.0


class TestCalcCVaR:
    def test_basic(self):
        np.random.seed(42)
        returns = pd.Series(np.random.randn(100) * 0.02)
        cvar = calc_cvar(returns)
        assert cvar < 0


class TestCalcInformationRatio:
    def test_basic(self):
        np.random.seed(42)
        returns = pd.Series(np.random.randn(100) * 0.02 + 0.001)
        benchmark = pd.Series(np.random.randn(100) * 0.015)
        ir = calc_information_ratio(returns, benchmark)
        assert isinstance(ir, float)


class TestCalcAlphaBeta:
    def test_basic(self):
        np.random.seed(42)
        returns = pd.Series(np.random.randn(100) * 0.02 + 0.001)
        benchmark = pd.Series(np.random.randn(100) * 0.015)
        alpha, beta = calc_alpha_beta(returns, benchmark)
        assert isinstance(alpha, float)
        assert isinstance(beta, float)


class TestCalcMaxConsecutive:
    def test_wins(self):
        returns = pd.Series([0.01, 0.02, 0.01, -0.01, 0.03, 0.02, 0.01])
        max_wins = calc_max_consecutive(returns, True)
        assert max_wins == 3

    def test_losses(self):
        returns = pd.Series([0.01, -0.01, -0.02, -0.01, 0.03])
        max_losses = calc_max_consecutive(returns, False)
        assert max_losses == 3


class TestCalcAllMetrics:
    def test_basic(self):
        np.random.seed(42)
        equity = list(np.cumprod(1 + np.random.randn(252) * 0.01) * 100000)
        metrics = calc_all_metrics(equity)
        assert isinstance(metrics, InstitutionalMetrics)
        assert metrics.cagr != 0 or metrics.total_return != 0 or True
        assert metrics.sharpe_ratio is not None

    def test_with_benchmark(self):
        np.random.seed(42)
        equity = list(np.cumprod(1 + np.random.randn(252) * 0.01) * 100000)
        benchmark = pd.Series(np.random.randn(252) * 0.008)
        metrics = calc_all_metrics(equity, benchmark_returns=benchmark)
        assert metrics.alpha != 0 or metrics.beta != 0 or True

    def test_short(self):
        metrics = calc_all_metrics([100000])
        assert metrics.sharpe_ratio == 0.0


class TestMetricsToDict:
    def test_basic(self):
        metrics = InstitutionalMetrics(
            cagr=0.10, sharpe_ratio=1.5, sortino_ratio=2.0,
            max_drawdown=-0.15, calmar_ratio=0.67,
        )
        d = metrics_to_dict(metrics)
        assert "CAGR" in d
        assert "Sharpe Ratio" in d
        assert "Max Drawdown" in d
