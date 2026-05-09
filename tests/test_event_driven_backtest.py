import numpy as np
import pandas as pd
import pytest

from core.backtest.event_driven import _calc_hold_days, run_event_driven
from core.backtest.engine import BacktestEngine
from core.backtest.result import InsufficientDataError
from core.strategies import BaseStrategy, SignalType, StrategyResult


class _SimpleBuyStrategy(BaseStrategy):
    name = "simple_buy"

    def __init__(self):
        super().__init__()
        self._bought = False

    def generate_signals(self, df: pd.DataFrame) -> StrategyResult:
        return StrategyResult(signals=[])

    def on_bar(self, bar: dict, portfolio: dict) -> list[dict]:
        if not self._bought and portfolio.get("cash", 0) > 10000:
            self._bought = True
            return [{"action": "buy", "position_pct": 0.3, "reason": "test buy"}]
        if self._bought and bar.get("close", 0) > 0 and portfolio.get("positions"):
            self._bought = False
            return [{"action": "sell", "reason": "test sell"}]
        return []


class _NeverBuyStrategy(BaseStrategy):
    name = "never_buy"

    def generate_signals(self, df: pd.DataFrame) -> StrategyResult:
        return StrategyResult(signals=[])

    def on_bar(self, bar: dict, portfolio: dict) -> list[dict]:
        return []


class _StopLossStrategy(BaseStrategy):
    name = "stop_loss_test"

    def generate_signals(self, df: pd.DataFrame) -> StrategyResult:
        return StrategyResult(signals=[])

    def __init__(self, stop_loss: float = 0.0, take_profit: float = 0.0):
        super().__init__()
        self._bought = False
        self._stop_loss = stop_loss
        self._take_profit = take_profit

    def on_bar(self, bar: dict, portfolio: dict) -> list[dict]:
        if not self._bought and portfolio.get("cash", 0) > 10000:
            self._bought = True
            return [{"action": "buy", "position_pct": 0.3, "stop_loss": self._stop_loss, "take_profit": self._take_profit, "reason": "test"}]
        return []


def _make_df(n: int = 30, start_price: float = 10.0, trend: float = 0.0) -> pd.DataFrame:
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = start_price + np.cumsum(np.random.normal(trend, 0.2, n))
    close = np.maximum(close, 1.0)
    return pd.DataFrame({
        "date": dates,
        "open": close * (1 + np.random.normal(0, 0.005, n)),
        "high": close * (1 + np.abs(np.random.normal(0, 0.01, n))),
        "low": close * (1 - np.abs(np.random.normal(0, 0.01, n))),
        "close": close,
        "volume": np.random.uniform(1e6, 1e7, n),
        "amount": np.random.uniform(1e7, 1e8, n),
    })


class TestCalcHoldDays:
    def test_valid_dates(self):
        assert _calc_hold_days("2024-01-01", "2024-01-11") == 10

    def test_same_day(self):
        assert _calc_hold_days("2024-01-01", "2024-01-01") == 0

    def test_empty_strings(self):
        assert _calc_hold_days("", "2024-01-01") == 0
        assert _calc_hold_days("2024-01-01", "") == 0

    def test_invalid_format(self):
        assert _calc_hold_days("not-a-date", "2024-01-01") == 0

    def test_reversed_dates(self):
        assert _calc_hold_days("2024-01-11", "2024-01-01") == 0


class TestRunEventDriven:
    def test_insufficient_data_raises(self):
        engine = BacktestEngine()
        strategy = _NeverBuyStrategy()
        df = _make_df(5)
        with pytest.raises(InsufficientDataError):
            run_event_driven(engine, strategy, df)

    def test_none_data_raises(self):
        engine = BacktestEngine()
        strategy = _NeverBuyStrategy()
        with pytest.raises(InsufficientDataError):
            run_event_driven(engine, strategy, None)

    def test_no_trades_strategy(self):
        engine = BacktestEngine(enable_data_quality=False)
        strategy = _NeverBuyStrategy()
        df = _make_df(30)
        result = run_event_driven(engine, strategy, df, enable_risk_check=False)
        assert result.total_trades == 0
        assert result.strategy_name == "_NeverBuyStrategy"

    def test_buy_sell_strategy(self):
        engine = BacktestEngine(enable_data_quality=False)
        strategy = _SimpleBuyStrategy()
        df = _make_df(30, start_price=10.0)
        result = run_event_driven(engine, strategy, df, enable_risk_check=False)
        assert result.total_trades >= 1
        assert len(result.equity_curve) > 0

    def test_stop_loss_triggered(self):
        engine = BacktestEngine(enable_data_quality=False)
        np.random.seed(42)
        n = 30
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        close = np.full(n, 10.0)
        close[10:] = 7.0
        low = close.copy()
        low[10:] = 6.5
        df = pd.DataFrame({
            "date": dates,
            "open": close,
            "high": close,
            "low": low,
            "close": close,
            "volume": np.full(n, 1e7),
            "amount": np.full(n, 1e8),
        })
        strategy = _StopLossStrategy(stop_loss=8.0)
        result = run_event_driven(engine, strategy, df, enable_risk_check=False)
        sell_trades = [t for t in result.trades if t.get("action") == "sell"]
        assert len(sell_trades) >= 1
        assert any("止损" in t.get("reason", "") for t in sell_trades)

    def test_result_has_statistics(self):
        engine = BacktestEngine(enable_data_quality=False)
        strategy = _SimpleBuyStrategy()
        df = _make_df(30)
        result = run_event_driven(engine, strategy, df, enable_risk_check=False)
        assert hasattr(result, "sharpe_ratio")
        assert hasattr(result, "max_drawdown")
        assert hasattr(result, "equity_curve")
        assert len(result.equity_curve) > 0
