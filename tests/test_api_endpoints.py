import random
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from main import app
    with TestClient(app) as c:
        yield c


class TestHealthAndRoot:
    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data


class TestMarketAPI:
    def test_market_overview(self, client):
        resp = client.get("/api/market/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_market_status(self, client):
        resp = client.get("/api/market/status")
        assert resp.status_code == 200

    def test_market_stocks(self, client):
        resp = client.get("/api/market/stocks")
        assert resp.status_code == 200

    def test_market_heatmap(self, client):
        resp = client.get("/api/market/heatmap")
        assert resp.status_code == 200

    def test_market_anomaly(self, client):
        resp = client.get("/api/market/anomaly")
        assert resp.status_code == 200

    def test_market_limit_up(self, client):
        resp = client.get("/api/market/limit_up")
        assert resp.status_code == 200

    def test_market_dragon_tiger(self, client):
        resp = client.get("/api/market/dragon_tiger")
        assert resp.status_code == 200

    def test_market_northbound(self, client):
        resp = client.get("/api/market/northbound/detail")
        assert resp.status_code == 200


class TestStockAPI:
    def test_stock_realtime(self, client):
        resp = client.get("/api/stock/realtime/600000")
        assert resp.status_code == 200

    def test_stock_history(self, client):
        resp = client.get("/api/stock/history/600000")
        assert resp.status_code == 200

    def test_stock_fundamentals(self, client):
        resp = client.get("/api/stock/fundamentals/600000")
        assert resp.status_code == 200

    def test_stock_indicators(self, client):
        resp = client.get("/api/stock/indicators/600000")
        assert resp.status_code == 200

    def test_stock_analysis(self, client):
        resp = client.get("/api/stock/analysis/600000")
        assert resp.status_code == 200

    def test_stock_signals(self, client):
        resp = client.get("/api/stock/signals/600000")
        assert resp.status_code == 200

    def test_stock_prediction(self, client):
        resp = client.get("/api/stock/prediction/600000")
        assert resp.status_code == 200

    def test_stock_correlation(self, client):
        resp = client.get("/api/stock/correlation/600000")
        assert resp.status_code == 200

    def test_stock_ai_summary(self, client):
        resp = client.get("/api/stock/ai_summary/600000")
        assert resp.status_code == 200

    def test_search(self, client):
        resp = client.get("/api/search", params={"q": "600000"})
        assert resp.status_code == 200


class TestTradingAPI:
    def test_trading_account(self, client):
        resp = client.get("/api/trading/account")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "total_assets" in data.get("data", {})

    def test_trading_buy(self, client):
        resp = client.post("/api/trading/buy", json={
            "symbol": "600000", "name": "浦发银行", "market": "A",
            "price": 10.0, "shares": 100, "market_price": 10.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_trading_sell_t1_restricted(self, client):
        resp = client.post("/api/trading/buy", json={
            "symbol": "601398", "name": "工商银行", "market": "A",
            "price": 5.0, "shares": 100, "market_price": 5.0,
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        sell_resp = client.post("/api/trading/sell", json={
            "symbol": "601398", "price": 5.5, "shares": 100,
        })
        assert sell_resp.status_code == 200
        data = sell_resp.json()
        assert data["success"] is False
        error_msg = data.get("error", "") or data.get("data", {}).get("error", "")
        assert "T+1" in error_msg

    def test_trading_sell_nonexistent(self, client):
        resp = client.post("/api/trading/sell", json={
            "symbol": "999999", "price": 10.0, "market_price": 10.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_trading_history(self, client):
        resp = client.get("/api/trading/history")
        assert resp.status_code == 200

    def test_trading_buy_insufficient_funds(self, client):
        resp = client.post("/api/trading/buy", json={
            "symbol": "600001", "name": "Test", "market": "A",
            "price": 99999.0, "shares": 9999, "market_price": 99999.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False


class TestBacktestAPI:
    def test_backtest_strategies(self, client):
        resp = client.get("/api/backtest/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_backtest_run(self, client):
        resp = client.post("/api/backtest/run", json={
            "symbol": "600000", "strategy_type": "dual_ma",
            "start_date": "2024-01-01", "end_date": "2024-12-31",
            "initial_capital": 1000000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_backtest_run_invalid_strategy(self, client):
        resp = client.post("/api/backtest/run", json={
            "symbol": "600000", "strategy_type": "nonexistent_strategy",
            "start_date": "2024-01-01", "end_date": "2024-12-31",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_backtest_compare(self, client):
        resp = client.get("/api/backtest/compare", params={
            "id1": "test-1",
            "id2": "test-2",
        })
        assert resp.status_code == 200

    def test_backtest_recommend(self, client):
        resp = client.get("/api/backtest/recommend", params={
            "symbol": "600000",
        })
        assert resp.status_code == 200

    def test_backtest_advanced(self, client):
        resp = client.post("/api/backtest/advanced", json={
            "symbol": "600000", "strategy_type": "dual_ma",
            "start_date": "2024-01-01", "end_date": "2024-12-31",
            "initial_capital": 1000000,
        })
        assert resp.status_code == 200

    def test_backtest_optimize(self, client):
        resp = client.post("/api/backtest/optimize", json={
            "symbol": "600000", "strategy_type": "dual_ma",
            "start_date": "2024-01-01", "end_date": "2024-12-31",
        })
        assert resp.status_code == 200

    def test_backtest_history(self, client):
        resp = client.get("/api/backtest/history")
        assert resp.status_code == 200

    def test_backtest_random_strategy(self, client):
        strategies = ["dual_ma", "macd", "kdj", "bollinger", "momentum", "rsi_mean_reversion"]
        for _ in range(3):
            strategy = random.choice(strategies)
            capital = random.choice([100000, 500000, 1000000, 5000000])
            resp = client.post("/api/backtest/run", json={
                "symbol": "600000", "strategy_type": strategy,
                "start_date": "2024-01-01", "end_date": "2024-12-31",
                "initial_capital": capital,
            })
            assert resp.status_code == 200


class TestFeatureAPI:
    def test_news_latest(self, client):
        resp = client.get("/api/news/latest")
        assert resp.status_code == 200

    def test_news_stock(self, client):
        resp = client.get("/api/news/stock/600000")
        assert resp.status_code == 200

    def test_news_sentiment(self, client):
        resp = client.get("/api/news/sentiment")
        assert resp.status_code == 200

    def test_screener_presets(self, client):
        resp = client.get("/api/screener/presets")
        assert resp.status_code == 200

    def test_screener_run(self, client):
        resp = client.get("/api/screener/run")
        assert resp.status_code == 200

    def test_screener_custom(self, client):
        resp = client.post("/api/screener/custom", json={
            "filters": {"min_price": 5, "max_price": 100},
        })
        assert resp.status_code == 200

    def test_moneyflow_stock(self, client):
        resp = client.get("/api/moneyflow/stock/600000")
        assert resp.status_code == 200

    def test_moneyflow_ranking(self, client):
        resp = client.get("/api/moneyflow/ranking")
        assert resp.status_code == 200

    def test_moneyflow_sector(self, client):
        resp = client.get("/api/moneyflow/sector")
        assert resp.status_code == 200

    def test_chip_analysis(self, client):
        resp = client.get("/api/chip/600000")
        assert resp.status_code == 200

    def test_sector_strength(self, client):
        resp = client.get("/api/sector/strength")
        assert resp.status_code == 200

    def test_sector_rotation(self, client):
        resp = client.get("/api/sector/rotation")
        assert resp.status_code == 200


class TestWatchlistAPI:
    def test_get_watchlist(self, client):
        resp = client.get("/api/watchlist")
        assert resp.status_code == 200

    def test_add_watchlist(self, client):
        resp = client.post("/api/watchlist/add", json={
            "symbol": "600000", "name": "浦发银行",
        })
        assert resp.status_code == 200

    def test_remove_watchlist(self, client):
        resp = client.post("/api/watchlist/remove", json={
            "symbol": "600000",
        })
        assert resp.status_code == 200


class TestSystemAPI:
    def test_system_metrics(self, client):
        resp = client.get("/api/system/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        metrics = data["data"]
        assert "uptime_seconds" in metrics
        assert "api_requests_total" in metrics
        assert "avg_response_time" in metrics
        assert "ws_connections" in metrics
        assert isinstance(metrics["uptime_seconds"], (int, float))
        assert isinstance(metrics["api_requests_total"], int)
        assert metrics["uptime_seconds"] >= 0

    def test_config_get(self, client):
        resp = client.get("/api/config/test_key")
        assert resp.status_code == 200


class TestAlphaAPI:
    def test_alpha_list(self, client):
        resp = client.get("/api/alpha/list")
        assert resp.status_code == 200

    def test_alpha_compute(self, client):
        resp = client.get("/api/alpha/compute/600000")
        assert resp.status_code == 200

    def test_regime_detect(self, client):
        resp = client.get("/api/regime/detect/600000")
        assert resp.status_code == 200

    def test_risk_monitor(self, client):
        resp = client.get("/api/risk/monitor/600000")
        assert resp.status_code == 200

    def test_institutional_metrics(self, client):
        resp = client.get("/api/metrics/institutional/600000")
        assert resp.status_code == 200


class TestPortfolioAPI:
    def test_portfolio_risk_analysis(self, client):
        resp = client.get("/api/portfolio/risk_analysis", params={"symbols": "600000,000001"})
        assert resp.status_code == 200

    def test_portfolio_attribution(self, client):
        resp = client.get("/api/portfolio/attribution", params={"symbols": "600000,000001"})
        assert resp.status_code == 200

    def test_portfolio_equity(self, client):
        resp = client.get("/api/portfolio/equity", params={"symbols": "600000,000001"})
        assert resp.status_code == 200

    def test_report_weekly(self, client):
        resp = client.get("/api/report/weekly")
        assert resp.status_code == 200
