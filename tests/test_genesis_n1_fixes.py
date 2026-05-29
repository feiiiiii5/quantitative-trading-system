from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest


class TestGetHistoryBatchParallel:
    def test_batch_fetch_calls_gather_not_serial(self):
        from core.data_fetcher import SmartDataFetcher

        fetcher = SmartDataFetcher.__new__(SmartDataFetcher)
        fetcher._health = MagicMock()
        fetcher._health.rank_sources.return_value = ["eastmoney"]

        df = pd.DataFrame({"close": [10.0, 11.0, 12.0], "volume": [100, 200, 300]})

        with patch.object(fetcher, "get_history", new_callable=AsyncMock, return_value=df):
            result = asyncio.run(
                fetcher.get_history_batch(["600519", "000858"], "1y", "daily", "qfq")
            )

        assert "600519" in result
        assert "000858" in result
        assert len(result) == 2

    def test_batch_fetch_handles_individual_failures(self):
        from core.data_fetcher import SmartDataFetcher

        fetcher = SmartDataFetcher.__new__(SmartDataFetcher)
        fetcher._health = MagicMock()
        fetcher._health.rank_sources.return_value = ["eastmoney"]

        good_df = pd.DataFrame({"close": [10.0], "volume": [100]})

        async def mock_get_history(symbol, *args, **kwargs):
            if symbol == "BAD":
                raise ConnectionError("source down")
            return good_df

        with patch.object(fetcher, "get_history", side_effect=mock_get_history):
            result = asyncio.run(
                fetcher.get_history_batch(["GOOD", "BAD"], "1y", "daily", "qfq")
            )

        assert "GOOD" in result
        assert "BAD" not in result

    def test_batch_fetch_limits_to_50_symbols(self):
        from core.data_fetcher import SmartDataFetcher

        fetcher = SmartDataFetcher.__new__(SmartDataFetcher)
        fetcher._health = MagicMock()
        fetcher._health.rank_sources.return_value = ["eastmoney"]

        good_df = pd.DataFrame({"close": [10.0], "volume": [100]})
        symbols = [f"SYM{i:04d}" for i in range(60)]

        with patch.object(fetcher, "get_history", new_callable=AsyncMock, return_value=good_df) as mock:
            asyncio.run(
                fetcher.get_history_batch(symbols, "1y", "daily", "qfq")
            )

        assert mock.call_count == 50


class TestSimulateLevel2FromDaily:
    def test_uses_real_depth_data_when_available(self):
        from core.data_fetcher import SmartDataFetcher

        fetcher = SmartDataFetcher.__new__(SmartDataFetcher)
        realtime = {
            "price": 100.0,
            "volume": 50000,
            "bid_prices": [99.99, 99.98, 99.97, 99.96, 99.95],
            "bid_volumes": [500, 400, 300, 200, 100],
            "ask_prices": [100.01, 100.02, 100.03, 100.04, 100.05],
            "ask_volumes": [600, 500, 400, 300, 200],
            "has_depth": True,
        }

        result = fetcher.simulate_level2_from_daily("600519", realtime)

        assert len(result["bids"]) == 5
        assert len(result["asks"]) == 5
        assert result["bids"][0]["price"] == 99.99
        assert result["bids"][0]["volume"] == 500
        assert result["asks"][0]["price"] == 100.01
        assert result["asks"][0]["volume"] == 600

    def test_falls_back_to_deterministic_when_no_depth(self):
        from core.data_fetcher import SmartDataFetcher

        fetcher = SmartDataFetcher.__new__(SmartDataFetcher)
        realtime = {
            "price": 100.0,
            "volume": 50000,
            "bid_prices": [],
            "bid_volumes": [],
            "ask_prices": [],
            "ask_volumes": [],
            "has_depth": False,
        }

        result = fetcher.simulate_level2_from_daily("600519", realtime)

        assert len(result["bids"]) > 0
        assert len(result["asks"]) > 0
        for bid in result["bids"]:
            assert bid["price"] < 100.0
        for ask in result["asks"]:
            assert ask["price"] > 100.0

    def test_deterministic_no_random_noise(self):
        from core.data_fetcher import SmartDataFetcher

        fetcher = SmartDataFetcher.__new__(SmartDataFetcher)
        realtime = {
            "price": 50.0,
            "volume": 10000,
            "bid_prices": [],
            "bid_volumes": [],
            "ask_prices": [],
            "ask_volumes": [],
            "has_depth": False,
        }

        r1 = fetcher.simulate_level2_from_daily("600519", realtime)
        r2 = fetcher.simulate_level2_from_daily("600519", realtime)

        for b1, b2 in zip(r1["bids"], r2["bids"], strict=False):
            assert b1["price"] == b2["price"]
            assert b1["volume"] == b2["volume"]

    def test_returns_empty_on_zero_price(self):
        from core.data_fetcher import SmartDataFetcher

        fetcher = SmartDataFetcher.__new__(SmartDataFetcher)
        realtime = {"price": 0, "volume": 0, "has_depth": False}

        result = fetcher.simulate_level2_from_daily("600519", realtime)

        assert result["bids"] == []
        assert result["asks"] == []


class TestBacktestDailyReturns:
    def test_daily_returns_computed_from_equity_curve(self):
        from core.backtest.parallel import _run_single_backtest, STRATEGY_REGISTRY
        from core.backtest.engine import BacktestEngine

        mock_result = MagicMock()
        mock_result.total_return = 0.1
        mock_result.sharpe_ratio = 1.5
        mock_result.max_drawdown = 0.05
        mock_result.trades = [
            {"action": "sell", "pnl": 100},
            {"action": "sell", "pnl": 200},
        ]
        mock_result.equity_curve = [100, 110, 121, 133.1]

        mock_cls = MagicMock(return_value=MagicMock())
        with patch.dict(STRATEGY_REGISTRY, {"test_strat": mock_cls}), \
             patch.object(BacktestEngine, "run", return_value=mock_result):
            result = _run_single_backtest((
                "test_strat", "test_strat", None,
                {"close": [10.0, 11.0], "volume": [100, 200]},
                "600519", 1000000,
            ))

        assert "daily_returns" in result
        dr = result["daily_returns"]
        assert len(dr) == 3
        assert abs(dr[0] - 0.1) < 1e-6
        assert abs(dr[1] - 0.1) < 1e-6

    def test_daily_returns_empty_for_short_equity(self):
        from core.backtest.parallel import _run_single_backtest, STRATEGY_REGISTRY
        from core.backtest.engine import BacktestEngine

        mock_result = MagicMock()
        mock_result.total_return = 0.0
        mock_result.sharpe_ratio = 0.0
        mock_result.max_drawdown = 0.0
        mock_result.trades = []
        mock_result.equity_curve = [100]

        mock_cls = MagicMock(return_value=MagicMock())
        with patch.dict(STRATEGY_REGISTRY, {"test_strat": mock_cls}), \
             patch.object(BacktestEngine, "run", return_value=mock_result):
            result = _run_single_backtest((
                "test_strat", "test_strat", None,
                {"close": [10.0], "volume": [100]},
                "600519", 1000000,
            ))

        assert result["daily_returns"] == []


class TestEastMoneyFiveLevelDepth:
    def test_fetch_realtime_parses_five_level_fields(self):
        from core.data_fetcher import EastMoneySource

        payload = {
            "data": {
                "f43": "1850", "f44": "100", "f45": "50", "f46": "200",
                "f47": "150", "f48": "0.50", "f57": "600519", "f58": "贵州茅台",
                "f60": "1848", "f116": "500000", "f117": "2000000",
                "f168": "1.5", "f169": "2.0", "f170": "0.5",
                "f19": "1849.99", "f20": "100", "f21": "1849.98", "f22": "200",
                "f23": "1849.97", "f24": "300", "f25": "1849.96", "f26": "400",
                "f27": "1849.95", "f28": "500",
                "f29": "1850.01", "f30": "150", "f31": "1850.02", "f32": "250",
                "f33": "1850.03", "f34": "350", "f35": "1850.04", "f36": "450",
                "f37": "1850.05", "f38": "550",
            }
        }
        mock_text = json.dumps(payload)

        with patch("core.data_fetcher.async_http_get", new_callable=AsyncMock, return_value=mock_text):
            result = asyncio.run(
                EastMoneySource.fetch_realtime("600519", "A")
            )

        assert result is not None
        assert len(result["bid_prices"]) == 5
        assert len(result["bid_volumes"]) == 5
        assert len(result["ask_prices"]) == 5
        assert len(result["ask_volumes"]) == 5
        assert result["bid_prices"][0] == 1849.99
        assert result["bid_volumes"][0] == 100
        assert result["ask_prices"][0] == 1850.01
        assert result["ask_volumes"][0] == 150
        assert result["has_depth"] is True

    def test_has_depth_false_when_no_volumes(self):
        from core.data_fetcher import EastMoneySource

        payload = {
            "data": {
                "f43": "1850", "f44": "-", "f45": "-", "f46": "-",
                "f47": "-", "f48": "-", "f57": "600519", "f58": "贵州茅台",
                "f60": "1848", "f116": "0", "f117": "0",
                "f168": "-", "f169": "-", "f170": "-",
                "f19": "-", "f20": "-", "f21": "-", "f22": "-",
                "f23": "-", "f24": "-", "f25": "-", "f26": "-",
                "f27": "-", "f28": "-",
                "f29": "-", "f30": "-", "f31": "-", "f32": "-",
                "f33": "-", "f34": "-", "f35": "-", "f36": "-",
                "f37": "-", "f38": "-",
            }
        }
        mock_text = json.dumps(payload)

        with patch("core.data_fetcher.async_http_get", new_callable=AsyncMock, return_value=mock_text):
            result = asyncio.run(
                EastMoneySource.fetch_realtime("600519", "A")
            )

        assert result is not None
        assert result["has_depth"] is False
