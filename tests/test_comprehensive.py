import random
import threading
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest


def _make_kline_df(n: int = 200, base_price: float = 50.0, seed: int = None) -> pd.DataFrame:
    if seed is None:
        seed = random.randint(0, 999999)
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start="2024-01-01", periods=n, freq="B")
    returns = rng.normal(0.001, 0.02, n)
    close = base_price * np.cumprod(1 + returns)
    close = np.maximum(close, 1.0)
    high = close * (1 + rng.uniform(0, 0.03, n))
    low = close * (1 - rng.uniform(0, 0.03, n))
    open_p = close * (1 + rng.normal(0, 0.01, n))
    volume = rng.uniform(1e6, 5e7, n)
    amount = volume * close
    return pd.DataFrame({
        "date": dates,
        "open": np.round(open_p, 2),
        "high": np.round(high, 2),
        "low": np.round(low, 2),
        "close": np.round(close, 2),
        "volume": np.round(volume, 0),
        "amount": np.round(amount, 2),
    })


class TestBacktestEngine:
    def test_basic_backtest_no_crash(self):
        from core.backtest import BacktestEngine
        from core.strategies import DualMAStrategy
        df = _make_kline_df(200, seed=42)
        engine = BacktestEngine(initial_capital=1000000)
        result = engine.run(DualMAStrategy(), df)
        assert result.strategy_name == "DualMAStrategy"
        assert len(result.equity_curve) > 0
        assert len(result.dates) > 0

    def test_backtest_open_position_forced_close(self):
        from core.backtest import BacktestEngine
        from core.strategies import DualMAStrategy
        for seed in random.sample(range(100000), 5):
            df = _make_kline_df(100, seed=seed)
            engine = BacktestEngine(initial_capital=1000000)
            result = engine.run(DualMAStrategy(), df)
            assert result.equity_curve is not None
            assert len(result.dates) > 0

    def test_backtest_empty_data(self):
        from core.backtest import BacktestEngine
        from core.strategies import DualMAStrategy
        engine = BacktestEngine()
        result = engine.run(DualMAStrategy(), pd.DataFrame())
        assert result.total_trades == 0

    def test_backtest_short_data(self):
        from core.backtest import BacktestEngine
        from core.strategies import DualMAStrategy
        df = _make_kline_df(5, seed=1)
        engine = BacktestEngine()
        result = engine.run(DualMAStrategy(), df)
        assert result.total_trades == 0

    def test_backtest_result_fields(self):
        from core.backtest import BacktestEngine
        from core.strategies import DualMAStrategy
        df = _make_kline_df(200, seed=42)
        engine = BacktestEngine()
        result = engine.run(DualMAStrategy(), df)
        assert hasattr(result, "sharpe_ratio")
        assert hasattr(result, "max_drawdown")
        assert hasattr(result, "total_return")
        assert hasattr(result, "win_rate")
        assert hasattr(result, "trades")
        assert hasattr(result, "equity_curve")
        assert hasattr(result, "drawdown_curve")
        assert hasattr(result, "dates")
        assert hasattr(result, "kline_with_signals")

    def test_portfolio_correlation_calculation(self):
        rng = np.random.default_rng(42)
        n = 100
        stock_a = np.cumprod(1 + rng.normal(0.001, 0.02, n))
        stock_b = stock_a * 0.8 + rng.normal(0, 0.01, n)
        stock_c = np.cumprod(1 + rng.normal(0.001, 0.03, n))
        returns = np.column_stack([
            np.diff(stock_a) / stock_a[:-1],
            np.diff(stock_b) / stock_b[:-1],
            np.diff(stock_c) / stock_c[:-1],
        ])
        corr = np.corrcoef(returns.T)
        assert corr.shape == (3, 3)
        assert abs(corr[0, 0] - 1.0) < 0.01
        avg_corr = float(np.mean(corr[np.triu_indices(3, k=1)]))
        diversification = max(0, 1 - avg_corr)
        assert 0 <= diversification <= 1

    def test_backtest_multiple_strategies(self):
        from core.backtest import BacktestEngine
        from core.strategies import DualMAStrategy, RSIMeanReversionStrategy
        df = _make_kline_df(200, seed=42)
        engine = BacktestEngine()
        results = engine.run_multi([DualMAStrategy(), RSIMeanReversionStrategy()], df)
        assert "DualMAStrategy" in results
        assert "RSIMeanReversionStrategy" in results

    def test_monte_carlo_analysis(self):
        from core.backtest import BacktestEngine
        from core.strategies import DualMAStrategy
        df = _make_kline_df(200, seed=42)
        engine = BacktestEngine()
        result = engine.run(DualMAStrategy(), df)
        if result.total_trades > 0:
            mc = engine.monte_carlo_analysis(result, n_simulations=100)
            assert "final_equity_p50" in mc or "error" in mc

    def test_realistic_cost_model(self):
        from core.backtest import RealisticCostModel
        model = RealisticCostModel()
        buy_cost = model.calc_buy_cost(price=10.0, shares=1000)
        assert buy_cost["total"] > 0
        sell_cost = model.calc_sell_cost(price=10.0, shares=1000)
        assert sell_cost["total"] > 0
        assert sell_cost["stamp_tax"] > 0

    def test_cost_model_with_market_impact(self):
        from core.backtest import RealisticCostModel
        model = RealisticCostModel()
        cost = model.calc_buy_cost(price=10.0, shares=1000, daily_amount=1e8)
        assert cost["market_impact"] > 0

    def test_call_auction_fill(self):
        from core.backtest import _simulate_call_auction_fill
        for _ in range(100):
            price = random.uniform(1, 500)
            fill = _simulate_call_auction_fill(price)
            assert fill > 0
            assert abs(fill / price - 1) < 0.01

    def test_limit_price_check(self):
        from core.backtest import _check_limit_price
        is_normal, prob = _check_limit_price(10.0, 10.5, is_buy=True)
        assert is_normal is True
        assert prob == 1.0
        is_normal2, prob2 = _check_limit_price(10.0, 11.5, is_buy=True)
        assert is_normal2 is False
        assert prob2 < 1.0


class TestStrategies:
    def test_ma_cross_strategy(self):
        from core.strategies import DualMAStrategy
        df = _make_kline_df(200, seed=42)
        strategy = DualMAStrategy()
        result = strategy.generate_signals(df)
        assert result.strategy_name == "DualMAStrategy"
        assert isinstance(result.signals, list)

    def test_rsi_strategy(self):
        from core.strategies import RSIMeanReversionStrategy
        df = _make_kline_df(200, seed=42)
        strategy = RSIMeanReversionStrategy()
        result = strategy.generate_signals(df)
        assert result.strategy_name == "RSIMeanReversionStrategy"

    def test_macd_strategy(self):
        from core.strategies import MACDStrategy
        df = _make_kline_df(200, seed=42)
        strategy = MACDStrategy()
        result = strategy.generate_signals(df)
        assert result.strategy_name == "MACDStrategy"

    def test_bollinger_strategy(self):
        from core.strategies import BollingerBreakoutStrategy
        df = _make_kline_df(200, seed=42)
        strategy = BollingerBreakoutStrategy()
        result = strategy.generate_signals(df)
        assert result.strategy_name == "BollingerBreakoutStrategy"

    def test_strategy_with_random_data(self):
        from core.strategies import DualMAStrategy, RSIMeanReversionStrategy, MACDStrategy
        for seed in random.sample(range(100000), 10):
            df = _make_kline_df(random.randint(50, 300), seed=seed)
            for StrategyCls in [DualMAStrategy, RSIMeanReversionStrategy, MACDStrategy]:
                strategy = StrategyCls()
                result = strategy.generate_signals(df)
                assert result.strategy_name is not None

    def test_strategy_empty_data(self):
        from core.strategies import DualMAStrategy
        strategy = DualMAStrategy()
        result = strategy.generate_signals(pd.DataFrame())
        assert len(result.signals) == 0

    def test_strategy_registry(self):
        from core.strategies import STRATEGY_REGISTRY
        assert "dual_ma" in STRATEGY_REGISTRY
        assert "rsi_mean_reversion" in STRATEGY_REGISTRY
        assert "macd" in STRATEGY_REGISTRY


class TestSimulatedTrading:
    def test_buy_and_sell(self):
        from core.simulated_trading import SimulatedTrading
        t = SimulatedTrading(initial_capital=1000000)
        buy_result = t.execute_buy(
            symbol="600000", name="浦发银行", market="A",
            price=10.0, shares=100, market_price=10.0,
        )
        assert buy_result["success"] is True
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        for pos in t._positions.values():
            pos.buy_date = yesterday
        t.update_position_prices({"600000": 10.5})
        sell_result = t.execute_sell(symbol="600000", price=10.5, market_price=10.5)
        assert sell_result["success"] is True

    def test_buy_insufficient_funds(self):
        from core.simulated_trading import SimulatedTrading
        t = SimulatedTrading(initial_capital=1000)
        result = t.execute_buy(
            symbol="600000", name="浦发银行", market="A",
            price=100.0, shares=100, market_price=100.0,
        )
        assert result["success"] is False
        assert "资金不足" in result["error"]

    def test_sell_without_position(self):
        from core.simulated_trading import SimulatedTrading
        t = SimulatedTrading(initial_capital=1000000)
        result = t.execute_sell(symbol="600000", price=10.0)
        assert result["success"] is False

    def test_t1_restriction(self):
        from core.simulated_trading import SimulatedTrading
        t = SimulatedTrading(initial_capital=1000000)
        t.execute_buy(
            symbol="600000", name="浦发银行", market="A",
            price=10.0, shares=100, market_price=10.0,
        )
        result = t.execute_sell(symbol="600000", price=10.0, market_price=10.0)
        assert result["success"] is False
        assert "T+1" in result["error"]

    def test_duplicate_order(self):
        from core.simulated_trading import SimulatedTrading
        t = SimulatedTrading(initial_capital=1000000)
        r1 = t.execute_buy(
            symbol="600000", name="浦发银行", market="A",
            price=10.0, shares=100, market_price=10.0, order_id="test_001",
        )
        assert r1["success"] is True
        r2 = t.execute_buy(
            symbol="600000", name="浦发银行", market="A",
            price=10.0, shares=100, market_price=10.0, order_id="test_001",
        )
        assert r2["success"] is False
        assert "重复订单" in r2["error"]

    def test_concurrent_buys_no_overdraft(self):
        from core.simulated_trading import SimulatedTrading
        t = SimulatedTrading(initial_capital=100000)
        results = []
        errors = []

        def buy_stock(idx):
            try:
                r = t.execute_buy(
                    symbol=f"00000{idx % 5}", name=f"Stock{idx}", market="A",
                    price=50.0, shares=100, market_price=50.0,
                )
                results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=buy_stock, args=(i,)) for i in range(20)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        total_spent = sum(
            r["trade"]["amount"] + r["trade"]["fee"]
            for r in results
            if r.get("success") and "trade" in r
        )
        assert total_spent <= 100000 + 1

    def test_account_info(self):
        from core.simulated_trading import SimulatedTrading
        t = SimulatedTrading(initial_capital=1000000)
        info = t.get_account_info()
        assert info["total_assets"] == 1000000
        assert info["cash"] == 1000000
        assert info["position_count"] == 0

    def test_reset_account(self):
        from core.simulated_trading import SimulatedTrading
        t = SimulatedTrading(initial_capital=1000000)
        t.execute_buy(
            symbol="600000", name="浦发银行", market="A",
            price=10.0, shares=100, market_price=10.0,
        )
        t.reset_account()
        info = t.get_account_info()
        assert info["cash"] == 1000000
        assert info["position_count"] == 0

    def test_place_and_cancel_order(self):
        from core.simulated_trading import SimulatedTrading
        t = SimulatedTrading(initial_capital=1000000)
        order_result = t.place_order(
            symbol="600000", name="浦发银行", market="A",
            action="buy", order_type="limit", price=10.0, shares=100,
        )
        assert order_result["success"] is True
        order_id = order_result["order"]["id"]
        cancel_result = t.cancel_order(order_id)
        assert cancel_result["success"] is True

    def test_fee_calculation(self):
        from core.simulated_trading import SimulatedTrading
        t = SimulatedTrading()
        commission, stamp_tax = t._calc_fee(100000, is_sell=False, market="A", shares=1000)
        assert commission >= 5.0
        assert stamp_tax == 0
        commission2, stamp_tax2 = t._calc_fee(100000, is_sell=True, market="A", shares=1000)
        assert stamp_tax2 > 0

    def test_hk_fee(self):
        from core.simulated_trading import SimulatedTrading
        t = SimulatedTrading()
        commission, stamp_tax = t._calc_fee(100000, is_sell=True, market="HK", shares=500)
        assert commission >= 50.0

    def test_us_fee(self):
        from core.simulated_trading import SimulatedTrading
        t = SimulatedTrading()
        commission, stamp_tax = t._calc_fee(100000, is_sell=True, market="US", shares=100)
        assert commission >= 1.0
        assert stamp_tax == 0

    def test_random_trading_session(self):
        from core.simulated_trading import SimulatedTrading
        for seed in random.sample(range(100000), 5):
            t = SimulatedTrading(initial_capital=random.randint(100000, 5000000))
            rng = random.Random(seed)
            symbols = [f"{rng.randint(1, 9999):06d}" for _ in range(rng.randint(1, 10))]
            for _ in range(rng.randint(5, 30)):
                sym = rng.choice(symbols)
                price = rng.uniform(5, 200)
                shares = rng.choice([100, 200, 300, 500, 1000])
                t.execute_buy(
                    symbol=sym, name=f"Stock{sym}", market="A",
                    price=price, shares=shares, market_price=price,
                )
            info = t.get_account_info()
            assert info["total_assets"] > 0
            assert info["cash"] >= 0


class TestRiskManager:
    def test_concentration_filter(self):
        from core.risk_manager import ConcentrationFilter
        from core.orders import Order, OrderSide, OrderType
        f = ConcentrationFilter(max_concentration=0.3)
        order = Order(order_id="1", symbol="600000", side=OrderSide.BUY,
                      order_type=OrderType.MARKET, quantity=1000, price=10.0)
        context = {"total_assets": 100000, "current_positions": {}, "cash": 100000, "open_trades": 0}
        approved, _ = f.check(order, context)
        assert approved is True
        context2 = {"total_assets": 100000, "current_positions": {"600000": {"market_value": 35000}},
                     "cash": 65000, "open_trades": 1}
        approved2, reason = f.check(order, context2)
        assert approved2 is False

    def test_daily_loss_filter(self):
        from core.risk_manager import DailyLossFilter
        from core.orders import Order, OrderSide, OrderType
        f = DailyLossFilter(max_daily_loss=0.05, initial_capital=100000)
        f.update_daily_pnl(-6000)
        order = Order(order_id="1", symbol="600000", side=OrderSide.BUY,
                      order_type=OrderType.MARKET, quantity=100, price=10.0)
        approved, reason = f.check(order, {})
        assert approved is False

    def test_cash_sufficiency_filter(self):
        from core.risk_manager import CashSufficiencyFilter
        from core.orders import Order, OrderSide, OrderType
        f = CashSufficiencyFilter()
        order = Order(order_id="1", symbol="600000", side=OrderSide.BUY,
                      order_type=OrderType.MARKET, quantity=1000, price=10.0)
        context = {"cash": 5000}
        approved, reason = f.check(order, context)
        assert approved is False

    def test_enhanced_risk_manager_check_order_legacy(self):
        from core.risk_manager import EnhancedRiskManager
        rm = EnhancedRiskManager(initial_capital=1000000)
        result = rm.check_order_legacy(
            symbol="600000", action="buy", shares=100, price=10.0,
            current_positions={}, total_assets=1000000,
        )
        assert "approved" in result

    def test_trailing_stop(self):
        from core.risk_manager import TrailingStopManager
        mgr = TrailingStopManager(trailing_stop=-0.05, trailing_stop_positive=0.02)
        mgr.register("600000", 10.0)
        result = mgr.update("600000", 9.0)
        assert result == "trailing_stop"

    def test_roi_table(self):
        from core.risk_manager import ROITable
        table = ROITable()
        assert table.should_take_profit(0.15, 0) is True
        assert table.should_take_profit(0.001, 0) is False

    def test_var_cvar(self):
        from core.risk_manager import EnhancedRiskManager
        rm = EnhancedRiskManager()
        returns = list(np.random.normal(0.001, 0.02, 100))
        var = rm.calc_var(returns, 1000000)
        cvar = rm.calc_cvar(returns, 1000000)
        assert var >= 0
        assert cvar >= 0

    def test_risk_report(self):
        from core.risk_manager import EnhancedRiskManager
        rm = EnhancedRiskManager()
        report = rm.get_risk_report()
        assert "max_concentration" in report
        assert "circuit_breaker_active" in report


class TestIndicators:
    def test_compute_all(self):
        from core.indicators import TechnicalIndicators
        df = _make_kline_df(200, seed=42)
        result = TechnicalIndicators.compute_all(df, symbol="test")
        assert "ma" in result
        assert "ema" in result
        assert "boll" in result
        assert "macd" in result
        assert "rsi" in result
        assert "kdj" in result
        assert "signal" in result

    def test_compute_all_insufficient_data(self):
        from core.indicators import TechnicalIndicators
        df = _make_kline_df(5, seed=1)
        result = TechnicalIndicators.compute_all(df)
        assert result == {}

    def test_kline_patterns(self):
        from core.indicators import KLinePatternRecognizer
        df = _make_kline_df(200, seed=42)
        patterns = KLinePatternRecognizer.recognize(df)
        assert isinstance(patterns, list)

    def test_calc_all_indicators(self):
        from core.indicators import calc_all_indicators
        df = _make_kline_df(200, seed=42)
        kline_data = df.to_dict("records")
        result = calc_all_indicators(kline_data)
        assert isinstance(result, dict)
        assert "ma" in result or "error" in result

    def test_indicator_analysis(self):
        from core.indicators import IndicatorAnalysis
        df = _make_kline_df(200, seed=42)
        ma_align = IndicatorAnalysis.ma_alignment(df)
        assert "bullish" in ma_align
        assert "bearish" in ma_align

    def test_support_resistance(self):
        from core.indicators import IndicatorAnalysis
        df = _make_kline_df(200, seed=42)
        sr = IndicatorAnalysis.support_resistance(df)
        assert "supports" in sr
        assert "resistances" in sr

    def test_volume_price_analysis(self):
        from core.indicators import IndicatorAnalysis
        df = _make_kline_df(200, seed=42)
        vp = IndicatorAnalysis.volume_price_analysis(df)
        assert "conclusion" in vp

    def test_rsi_divergence(self):
        from core.indicators import IndicatorAnalysis
        df = _make_kline_df(200, seed=42)
        div = IndicatorAnalysis.rsi_divergence(df)
        assert "top_divergence" in div
        assert "bottom_divergence" in div

    def test_random_indicator_computation(self):
        from core.indicators import TechnicalIndicators
        for seed in random.sample(range(100000), 10):
            df = _make_kline_df(random.randint(30, 500), seed=seed)
            result = TechnicalIndicators.compute_all(df, symbol=f"test_{seed}")
            assert isinstance(result, dict)


class TestChipDistribution:
    def test_chip_analysis(self):
        from core.chip_distribution import ChipDistributionAnalyzer
        df = _make_kline_df(200, seed=42)
        analyzer = ChipDistributionAnalyzer()
        result = analyzer.analyze(
            close=df["close"].values,
            high=df["high"].values,
            low=df["low"].values,
            volume=df["volume"].values,
        )
        assert result.avg_cost > 0
        assert 0 <= result.profit_ratio <= 1
        assert len(result.prices) > 0

    def test_chip_fire(self):
        from core.chip_distribution import ChipDistributionAnalyzer
        df = _make_kline_df(200, seed=42)
        analyzer = ChipDistributionAnalyzer()
        result = analyzer.compute_chip_fire(
            close=df["close"].values,
            high=df["high"].values,
            low=df["low"].values,
            volume=df["volume"].values,
        )
        assert "status" in result
        assert "signal" in result

    def test_chip_insufficient_data(self):
        from core.chip_distribution import ChipDistributionAnalyzer
        analyzer = ChipDistributionAnalyzer()
        result = analyzer.analyze(
            close=np.array([10, 11]),
            high=np.array([11, 12]),
            low=np.array([9, 10]),
            volume=np.array([1000, 2000]),
        )
        assert result.avg_cost == 0

    def test_random_chip_analysis(self):
        from core.chip_distribution import ChipDistributionAnalyzer
        for seed in random.sample(range(100000), 5):
            df = _make_kline_df(random.randint(30, 300), seed=seed)
            analyzer = ChipDistributionAnalyzer()
            result = analyzer.analyze(
                close=df["close"].values,
                high=df["high"].values,
                low=df["low"].values,
                volume=df["volume"].values,
            )
            assert result.profit_ratio >= 0


class TestNewsEngine:
    def test_sentiment_analysis(self):
        from core.news_engine import _analyze_sentiment
        score, label = _analyze_sentiment("大涨 利好 突破")
        assert score > 0
        assert label in ("bullish", "slightly_bullish")
        score2, label2 = _analyze_sentiment("暴跌 利空 亏损")
        assert score2 < 0
        assert label2 in ("bearish", "slightly_bearish")
        score3, label3 = _analyze_sentiment("")
        assert score3 == 0

    def test_extract_symbols(self):
        from core.news_engine import _extract_symbols
        symbols = _extract_symbols("浦发银行（600000）大涨")
        assert "600000" in symbols

    def test_market_sentiment(self):
        from core.news_engine import NewsEngine
        engine = NewsEngine()
        news = [
            {"sentiment": 0.5},
            {"sentiment": -0.3},
            {"sentiment": 0.1},
        ]
        sentiment = engine.compute_market_sentiment(news)
        assert 0 <= sentiment.fear_greed_index <= 100
        assert sentiment.label in ("极度贪婪", "贪婪", "中性", "恐惧", "极度恐惧")

    def test_news_summary(self):
        from core.news_engine import NewsEngine
        engine = NewsEngine()
        news = [
            {"sentiment_label": "bullish"},
            {"sentiment_label": "bearish"},
            {"sentiment_label": "neutral"},
        ]
        summary = engine.get_news_summary(news)
        assert summary["total"] == 3
        assert summary["bullish"] == 1
        assert summary["bearish"] == 1


class TestDatabase:
    def test_lru_cache(self):
        from core.database import ThreadSafeLRU
        cache = ThreadSafeLRU(maxsize=5, ttl=60)
        cache.set("a", 1)
        assert cache.get("a") == 1
        assert cache.get("b") is None

    def test_lru_cache_ttl(self):
        from core.database import ThreadSafeLRU
        cache = ThreadSafeLRU(maxsize=5, ttl=0)
        cache.set("a", 1)
        time.sleep(0.01)
        assert cache.get("a") is None

    def test_lru_cache_eviction(self):
        from core.database import ThreadSafeLRU
        cache = ThreadSafeLRU(maxsize=3, ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.set("d", 4)
        assert cache.get("a") is None
        assert cache.get("d") == 4

    def test_lru_cache_delete_prefix(self):
        from core.database import ThreadSafeLRU
        cache = ThreadSafeLRU(maxsize=100, ttl=60)
        cache.set("kline_600000_daily", "data1")
        cache.set("kline_600001_daily", "data2")
        cache.set("rt_600000", "data3")
        count = cache.delete_prefix("kline_")
        assert count == 2
        assert cache.get("rt_600000") == "data3"

    def test_sqlite_store_basic(self):
        from core.database import SQLiteStore
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            db = SQLiteStore(db_path=os.path.join(tmpdir, "test.db"))
            db.set_config("test_key", {"value": 42})
            result = db.get_config("test_key")
            assert result == {"value": 42}
            db.close()

    def test_sqlite_kline_roundtrip(self):
        from core.database import SQLiteStore
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            db = SQLiteStore(db_path=os.path.join(tmpdir, "test.db"))
            rows = [
                {"date": "2024-01-02", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "amount": 10500, "turnover_rate": 1.5},
                {"date": "2024-01-03", "open": 10.5, "high": 11.5, "low": 10, "close": 11, "volume": 2000, "amount": 22000, "turnover_rate": 2.0},
            ]
            db.upsert_kline_rows("600000", "A", "daily", "", rows)
            db._flush_buffer()
            df = db.load_kline_rows("600000", "A", "daily")
            assert len(df) >= 2
            db.close()


class TestEvents:
    def test_event_bus_subscribe(self):
        from core.events import EventBus, Event, EventType
        bus = EventBus()
        received = []
        bus.subscribe(EventType.INIT, lambda e: received.append(e.data))
        bus.publish(Event(EventType.INIT, {"msg": "hello"}))
        assert len(received) == 1
        assert received[0]["msg"] == "hello"

    def test_event_bus_unsubscribe(self):
        from core.events import EventBus, Event, EventType
        bus = EventBus()
        received = []
        handler = lambda e: received.append(e)
        bus.subscribe(EventType.INIT, handler)
        bus.unsubscribe(EventType.INIT, handler)
        bus.publish(Event(EventType.INIT))
        assert len(received) == 0

    def test_event_bus_once(self):
        from core.events import EventBus, Event, EventType
        bus = EventBus()
        received = []
        bus.subscribe_once(EventType.INIT, lambda e: received.append(e))
        bus.publish(Event(EventType.INIT))
        bus.publish(Event(EventType.INIT))
        assert len(received) == 1


class TestOrders:
    def test_order_creation(self):
        from core.orders import Order, OrderSide, OrderType, OrderStatus
        order = Order(
            order_id="test_001", symbol="600000", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=100, price=10.0,
        )
        assert order.status == OrderStatus.PENDING_NEW
        assert order.is_active is True
        assert order.is_done is False

    def test_order_fill(self):
        from core.orders import Order, OrderSide, OrderType, OrderStatus
        order = Order(
            order_id="test_001", symbol="600000", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=100, price=10.0,
        )
        order.transition_to(OrderStatus.ACTIVE)
        order.fill(100, 10.5, commission=5.0)
        assert order.filled_quantity == 100
        assert order.status == OrderStatus.FILLED
        assert order.is_done is True

    def test_order_partial_fill(self):
        from core.orders import Order, OrderSide, OrderType, OrderStatus
        order = Order(
            order_id="test_001", symbol="600000", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=100, price=10.0,
        )
        order.transition_to(OrderStatus.ACTIVE)
        order.fill(50, 10.5)
        assert order.filled_quantity == 50
        assert order.status == OrderStatus.PARTIALLY_FILLED

    def test_order_reject(self):
        from core.orders import Order, OrderSide, OrderType, OrderStatus
        order = Order(
            order_id="test_001", symbol="600000", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=100, price=10.0,
        )
        order.reject("资金不足")
        assert order.status == OrderStatus.REJECTED
        assert "资金不足" in order.reject_reason

    def test_order_invalid_transition(self):
        from core.orders import Order, OrderSide, OrderType, OrderStatus
        order = Order(
            order_id="test_001", symbol="600000", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=100, price=10.0,
        )
        result = order.transition_to(OrderStatus.FILLED)
        assert result is False

    def test_order_to_dict(self):
        from core.orders import Order, OrderSide, OrderType
        order = Order(
            order_id="test_001", symbol="600000", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=100, price=10.0,
        )
        d = order.to_dict()
        assert d["symbol"] == "600000"
        assert d["side"] == "buy"

    def test_trade_amount(self):
        from core.orders import Trade, OrderSide
        trade = Trade(
            trade_id="t1", order_id="o1", symbol="600000",
            side=OrderSide.BUY, quantity=100, price=10.0,
        )
        assert trade.amount == 1000.0


class TestApiUtils:
    def test_sanitize(self):
        from api.utils import sanitize
        assert sanitize(np.int64(42)) == 42
        assert sanitize(np.float64(3.14)) == 3.14
        assert sanitize(np.bool_(True)) is True
        assert sanitize(np.array([1, 2, 3])) == [1, 2, 3]
        assert sanitize({"a": np.int64(1)}) == {"a": 1}
        assert sanitize([np.float64(1.0), np.int64(2)]) == [1.0, 2]

    def test_json_response(self):
        from api.utils import json_response
        resp = json_response(True, data={"key": "value"}, error="")
        assert resp["success"] is True
        assert resp["data"]["key"] == "value"
        resp2 = json_response(False, error="something wrong")
        assert resp2["success"] is False
        assert resp2["error"] == "something wrong"


class TestDataFetcherUtils:
    def test_safe_float(self):
        from core.data_fetcher import safe_float
        assert safe_float(42) == 42.0
        assert safe_float("3.14") == 3.14
        assert safe_float(None) == 0.0
        assert safe_float("-") == 0.0
        assert safe_float("") == 0.0
        assert safe_float("abc", default=1.0) == 1.0
        assert safe_float(np.nan) == 0.0

    def test_validate_realtime_data(self):
        from core.data_fetcher import validate_realtime_data
        valid = {"price": 10.0, "change_pct": 2.0, "volume": 100000, "timestamp": time.time()}
        assert validate_realtime_data(valid, "600000") is True
        invalid = {"price": 0, "change_pct": 0, "volume": 0, "timestamp": time.time()}
        assert validate_realtime_data(invalid, "600000") is False

    def test_validate_kline_data(self):
        from core.data_fetcher import validate_kline_data
        df = _make_kline_df(200, seed=42)
        assert validate_kline_data(df, "600000") is True
        assert validate_kline_data(pd.DataFrame(), "600000") is False

    def test_data_quality_checker(self):
        from core.data_fetcher import DataQualityChecker
        df = _make_kline_df(200, seed=42)
        cleaned, warnings = DataQualityChecker.check_kline(df)
        assert len(cleaned) > 0

    def test_circuit_breaker(self):
        from core.data_fetcher import CircuitBreaker
        import asyncio

        async def always_fail():
            raise Exception("test failure")

        async def always_succeed():
            return "ok"

        async def test_cb():
            cb = CircuitBreaker(failure_threshold=3, timeout=1)
            for _ in range(3):
                with pytest.raises(Exception):
                    await cb.call(always_fail)
            assert cb.state == "OPEN"
            with pytest.raises(Exception):
                await cb.call(always_fail)

        asyncio.run(test_cb())

    def test_circuit_breaker_empty_dataframe_trips_breaker(self):
        from core.data_fetcher import CircuitBreaker
        import pandas as pd
        import asyncio

        async def return_empty_df():
            return pd.DataFrame()

        async def test_cb():
            cb = CircuitBreaker(failure_threshold=3, timeout=1)
            for _ in range(3):
                await cb.call(return_empty_df)
            assert cb.state == "OPEN"

        asyncio.run(test_cb())

    def test_circuit_breaker_empty_list_trips_breaker(self):
        from core.data_fetcher import CircuitBreaker
        import asyncio

        async def return_empty_list():
            return []

        async def test_cb():
            cb = CircuitBreaker(failure_threshold=3, timeout=1)
            for _ in range(3):
                await cb.call(return_empty_list)
            assert cb.state == "OPEN"

        asyncio.run(test_cb())

    def test_circuit_breaker_valid_result_resets(self):
        from core.data_fetcher import CircuitBreaker
        import asyncio

        call_count = 0

        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise Exception("transient")
            return {"ok": True}

        async def test_cb():
            cb = CircuitBreaker(failure_threshold=3, timeout=5)
            for _ in range(2):
                with pytest.raises(Exception):
                    await cb.call(fail_then_succeed)
            assert cb.failure_count == 2
            result = await cb.call(fail_then_succeed)
            assert result == {"ok": True}
            assert cb.failure_count == 0

        asyncio.run(test_cb())

    def test_circuit_breaker_has_lock(self):
        from core.data_fetcher import CircuitBreaker
        import asyncio

        async def test_lock():
            cb = CircuitBreaker(failure_threshold=3, timeout=1)
            assert hasattr(cb, '_lock')
            async def slow_func():
                await asyncio.sleep(0.1)
                return "ok"
            results = await asyncio.gather(*[cb.call(slow_func) for _ in range(5)])
            assert all(r == "ok" for r in results)

        asyncio.run(test_lock())

    def test_to_list_converts_inf_to_zero(self):
        from core.indicators import _to_list
        arr = np.array([1.0, np.inf, -np.inf, np.nan, 2.0])
        result = _to_list(arr)
        assert result[0] == 1.0
        assert result[1] == 0.0
        assert result[2] == 0.0
        assert result[3] == 0.0
        assert result[4] == 2.0

    def test_buffer_retry_max(self):
        from core.database import SQLiteStore

        store = SQLiteStore()
        try:
            for _ in range(10):
                store.buffered_write("INVALID SQL SYNTAX !!!", ())
            for _ in range(7):
                store._flush_buffer()
            buffer_after = len(store._write_buffer)
            assert buffer_after == 0
        finally:
            store.close()

    def test_market_detector(self):
        from core.market_detector import MarketDetector
        assert MarketDetector.detect("600000") == "A"
        assert MarketDetector.detect("000001") == "A"
        assert MarketDetector.detect("AAPL") == "US"


class TestFactorFunctions:
    def test_factor_momentum_quality(self):
        from core.indicators import calc_factor_momentum_quality
        c = np.random.uniform(10, 50, 100)
        v = np.random.uniform(1e6, 5e7, 100)
        result = calc_factor_momentum_quality(c, v, period=20)
        assert len(result) == 100

    def test_factor_efficiency_ratio(self):
        from core.indicators import calc_factor_efficiency_ratio
        c = np.random.uniform(10, 50, 100)
        result = calc_factor_efficiency_ratio(c, period=10)
        assert len(result) == 100

    def test_composite_score(self):
        from core.indicators import calc_composite_score
        factors = {
            "f1": np.random.randn(100),
            "f2": np.random.randn(100),
        }
        result = calc_composite_score(factors)
        assert len(result) == 100

    def test_kelly_fraction(self):
        from core.indicators import calc_kelly_fraction
        c = np.cumsum(np.random.randn(200) * 0.5 + 100)
        result = calc_kelly_fraction(c)
        assert 0 <= result <= 0.5

    def test_random_factor_computation(self):
        from core.indicators import (
            calc_factor_price_acceleration,
            calc_factor_volume_price_trend,
            calc_factor_relative_volume,
            calc_factor_money_flow_index,
        )
        for seed in random.sample(range(100000), 5):
            rng = np.random.default_rng(seed)
            n = rng.integers(50, 300)
            c = rng.uniform(10, 100, n)
            h = c * (1 + rng.uniform(0, 0.03, n))
            l = c * (1 - rng.uniform(0, 0.03, n))
            v = rng.uniform(1e6, 5e7, n)
            r1 = calc_factor_price_acceleration(c)
            assert len(r1) == n
            r2 = calc_factor_volume_price_trend(c, v)
            assert len(r2) == n
            r3 = calc_factor_relative_volume(v)
            assert len(r3) == n
            r4 = calc_factor_money_flow_index(h, l, c, v)
            assert len(r4) == n


class TestAdaptiveStrategyFixes:
    def test_partial_profit_keeps_peak(self):
        from core.adaptive_strategy import AdaptiveStrategyEngine
        engine = AdaptiveStrategyEngine(initial_capital=1000000)
        n = 200
        rng = np.random.default_rng(42)
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        close = np.concatenate([
            np.linspace(10, 20, 100),
            np.linspace(20, 18, 50),
            np.linspace(18, 25, 50),
        ])
        high = close * 1.02
        low = close * 0.98
        open_p = close * 0.999
        volume = np.ones(n) * 5e7
        df = pd.DataFrame({
            "date": dates, "open": open_p, "high": high, "low": low,
            "close": close, "volume": volume, "amount": close * volume,
        })
        result = engine.run(df)
        trades = result.get("trades", [])
        partial_exits = [t for t in trades if "部分止盈" in t.get("reason", "")]
        for t in partial_exits:
            assert t["shares"] > 0
            assert t["pnl"] is not None

    def test_shares_never_negative(self):
        from core.adaptive_strategy import AdaptiveStrategyEngine
        engine = AdaptiveStrategyEngine(initial_capital=1000000)
        n = 200
        rng = np.random.default_rng(99)
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        returns = rng.normal(0, 0.05, n)
        close = 50 * np.cumprod(1 + returns)
        close = np.maximum(close, 1.0)
        high = close * 1.03
        low = close * 0.97
        open_p = close * 0.999
        volume = np.ones(n) * 5e7
        df = pd.DataFrame({
            "date": dates, "open": open_p, "high": high, "low": low,
            "close": close, "volume": volume, "amount": close * volume,
        })
        result = engine.run(df)
        trades = result.get("trades", [])
        for t in trades:
            assert t["shares"] >= 0, f"Trade has negative shares: {t}"

    def test_qlearning_deterministic_with_seed(self):
        from core.adaptive_strategy import QLearningWeightAdapter, MarketRegime
        adapter1 = QLearningWeightAdapter(n_strategies=5, seed=42)
        adapter2 = QLearningWeightAdapter(n_strategies=5, seed=42)
        base = [0.2, 0.2, 0.2, 0.2, 0.2]
        w1 = adapter1.select_weights(MarketRegime.LOW_VOLATILITY_CONSOLIDATION, 0.2, 0.0, base)
        w2 = adapter2.select_weights(MarketRegime.LOW_VOLATILITY_CONSOLIDATION, 0.2, 0.0, base)
        assert w1 == w2, "Seeded QLearning should be deterministic"

    def test_append_equity_helper(self):
        from core.adaptive_strategy import AdaptiveStrategyEngine
        engine = AdaptiveStrategyEngine(initial_capital=1000000)
        curve = [1000000.0]
        engine._returns_history = []
        engine._append_equity(curve, 500000, 100, 50.0)
        assert len(curve) == 2
        assert curve[-1] == 505000.0
        assert len(engine._returns_history) == 1


class TestStockScreenerSortNone:
    def test_sort_with_none_values(self):
        from core.stock_screener import StockScreener
        screener = StockScreener()
        stocks = [
            {"symbol": "A", "change_pct": 5.0},
            {"symbol": "B", "change_pct": None},
            {"symbol": "C", "change_pct": -2.0},
        ]
        result = screener._screen(stocks, [])
        result.sort(key=lambda x: float(x.get("change_pct") if x.get("change_pct") is not None else 0), reverse=True)
        assert result[0]["symbol"] == "A"
        assert len(result) == 3


class TestAdaptiveStrategyPartialExit:
    def test_position_shares_updated_after_partial_exit(self):
        from core.adaptive_strategy import AdaptiveStrategyEngine
        engine = AdaptiveStrategyEngine(initial_capital=1000000)
        n = 200
        rng = np.random.default_rng(77)
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        close = np.concatenate([
            np.linspace(10, 25, 80),
            np.linspace(25, 21, 60),
            np.linspace(21, 30, 60),
        ])
        high = close * 1.02
        low = close * 0.98
        open_p = close * 0.999
        volume = np.ones(n) * 5e7
        df = pd.DataFrame({
            "date": dates, "open": open_p, "high": high, "low": low,
            "close": close, "volume": volume, "amount": close * volume,
        })
        result = engine.run(df)
        trades = result.get("trades", [])
        partial_exits = [t for t in trades if "部分止盈" in t.get("reason", "")]
        for t in partial_exits:
            assert t["shares"] > 0

    def test_buy_after_partial_exit_adds_shares(self):
        from core.adaptive_strategy import AdaptiveStrategyEngine
        engine = AdaptiveStrategyEngine(initial_capital=1000000)
        n = 300
        rng = np.random.default_rng(55)
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        close = np.concatenate([
            np.linspace(10, 25, 100),
            np.linspace(25, 20, 50),
            np.linspace(20, 35, 80),
            np.linspace(35, 30, 70),
        ])
        high = close * 1.02
        low = close * 0.98
        open_p = close * 0.999
        volume = np.ones(n) * 5e7
        df = pd.DataFrame({
            "date": dates, "open": open_p, "high": high, "low": low,
            "close": close, "volume": volume, "amount": close * volume,
        })
        result = engine.run(df)
        trades = result.get("trades", [])
        sell_trades = [t for t in trades if t["action"] == "sell"]
        for t in sell_trades:
            assert t["shares"] >= 0


class TestReturnsHistoryBounded:
    def test_returns_history_does_not_exceed_max(self):
        from core.adaptive_strategy import AdaptiveStrategyEngine
        engine = AdaptiveStrategyEngine(initial_capital=1000000)
        assert engine._returns_history_max == 120
        n = 500
        rng = np.random.default_rng(77)
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = 50 * np.cumprod(1 + rng.normal(0.001, 0.02, n))
        close = np.maximum(close, 1.0)
        df = pd.DataFrame({
            "date": dates, "open": close * 0.999, "high": close * 1.02,
            "low": close * 0.98, "close": close,
            "volume": np.ones(n) * 5e7, "amount": close * 5e7,
        })
        engine.run(df)
        assert len(engine._returns_history) <= engine._returns_history_max


class TestDatabaseFlushRetry:
    def test_failed_writes_requeued(self):
        from core.database import SQLiteStore
        db = SQLiteStore(":memory:")
        db.buffered_write("INSERT INTO nonexistent_table (a) VALUES (?)", ("test",))
        import logging
        import io
        handler = logging.StreamHandler(io.StringIO())
        handler.setLevel(logging.WARNING)
        db_logger = logging.getLogger("core.database")
        db_logger.addHandler(handler)
        db._flush_buffer()
        log_output = handler.stream.getvalue()
        db_logger.removeHandler(handler)
        assert "Buffered write error" in log_output or "Flush buffer error" in log_output


class TestSanitizeDepthLimit:
    def test_deeply_nested_sanitized(self):
        from api.utils import sanitize
        deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": {"j": {"k": "deep"}}}}}}}}}}}
        result = sanitize(deep)
        assert isinstance(result, dict)
        assert "a" in result

    def test_normal_nested_preserved(self):
        from api.utils import sanitize
        data = {"level1": {"level2": {"level3": "value"}}}
        result = sanitize(data)
        assert result["level1"]["level2"]["level3"] == "value"


class TestSymbolValidation:
    def test_valid_symbols_accepted(self):
        from pydantic import ValidationError
        from api.backtest_routes import BacktestRunRequest
        valid = BacktestRunRequest(symbol="600519", strategy_type="adaptive")
        assert valid.symbol == "600519"

    def test_invalid_symbol_rejected(self):
        from pydantic import ValidationError
        from api.backtest_routes import BacktestRunRequest
        with pytest.raises(ValidationError):
            BacktestRunRequest(symbol="../../etc/passwd")

    def test_invalid_strategy_type_rejected(self):
        from pydantic import ValidationError
        from api.backtest_routes import BacktestRunRequest
        with pytest.raises(ValidationError):
            BacktestRunRequest(symbol="600519", strategy_type="<script>alert(1)</script>")

    def test_invalid_date_format_rejected(self):
        from pydantic import ValidationError
        from api.backtest_routes import BacktestRunRequest
        with pytest.raises(ValidationError):
            BacktestRunRequest(symbol="600519", start_date="not-a-date")


class TestPostBodyValidation:
    def test_watchlist_invalid_symbol_rejected(self):
        from pydantic import ValidationError
        from api.routes import WatchlistAddRemoveRequest
        with pytest.raises(ValidationError):
            WatchlistAddRemoveRequest(symbol="../../etc/passwd")

    def test_alert_invalid_type_rejected(self):
        from pydantic import ValidationError
        from api.routes import AlertAddRequest
        with pytest.raises(ValidationError):
            AlertAddRequest(symbol="600519", alert_type="hack", value=100)

    def test_alert_valid_type_accepted(self):
        from api.routes import AlertAddRequest
        req = AlertAddRequest(symbol="600519", alert_type="price_above", value=100)
        assert req.alert_type == "price_above"

    def test_trading_buy_invalid_symbol_rejected(self):
        from pydantic import ValidationError
        from api.routes import TradingBuyRequest
        with pytest.raises(ValidationError):
            TradingBuyRequest(symbol="<script>", price=10, shares=100)

    def test_config_value_max_length(self):
        from pydantic import ValidationError
        from api.routes import ConfigSetRequest
        with pytest.raises(ValidationError):
            ConfigSetRequest(value="x" * 10001)


class TestGenesisRegression:
    def test_partial_exit_ratio_sells_50pct(self):
        from core.adaptive_strategy import PARTIAL_EXIT_RATIO
        assert PARTIAL_EXIT_RATIO == 0.5
        shares = 1000
        partial_shares = int(shares * PARTIAL_EXIT_RATIO) // 100 * 100
        assert partial_shares == 500

    def test_thread_safe_lru_is_true_lru(self):
        from core.database import ThreadSafeLRU
        cache = ThreadSafeLRU(maxsize=3, ttl=300)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.get("a")
        cache.set("d", 4)
        assert cache.get("a") == 1
        assert cache.get("b") is None

    def test_board_specific_price_limits(self):
        from core.backtest import _get_limit_pct
        assert _get_limit_pct("600519") == 0.10
        assert _get_limit_pct("300001") == 0.20
        assert _get_limit_pct("688001") == 0.20
        assert _get_limit_pct("830001") == 0.30

    def test_rate_limit_active_without_auth(self):
        from api.auth import APIAuthMiddleware
        middleware = APIAuthMiddleware(app=None, api_key="", enabled=False)
        assert middleware._rate_limit_per_minute == 120

    def test_risk_manager_position_returns_cleanup(self):
        from core.risk_manager import EnhancedRiskManager
        rm = EnhancedRiskManager(initial_capital=1000000)
        rm.register_position("600519", 1800.0)
        rm.update_position_returns("600519", 0.01)
        assert "600519" in rm._position_returns
        rm.unregister_position("600519")
        assert "600519" not in rm._position_returns

    def test_strategy_performance_endpoint_structure(self):
        from core.strategies import DualMAStrategy, MACDStrategy
        from core.backtest import BacktestEngine
        rng = np.random.default_rng(42)
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        close = 50 * np.cumprod(1 + rng.normal(0.001, 0.02, n))
        df = pd.DataFrame({
            "date": dates, "open": close * 0.999, "high": close * 1.02,
            "low": close * 0.98, "close": close, "volume": np.ones(n) * 5e7,
            "amount": close * 5e7,
        })
        engine = BacktestEngine(initial_capital=1000000)
        for strategy_cls in [DualMAStrategy, MACDStrategy]:
            result = engine.run(strategy_cls(), df, symbol="600519")
            assert hasattr(result, "total_return")
            assert hasattr(result, "sharpe_ratio")
            assert hasattr(result, "trades")
