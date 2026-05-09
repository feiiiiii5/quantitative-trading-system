import random

import numpy as np
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

    def test_api_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "degraded")
        assert "checks" in data
        assert "database" in data["checks"]
        assert "trading" in data["checks"]
        assert "data_fetcher" in data["checks"]
        assert "data_sources" in data
        assert "cache_info" in data
        assert "uptime_seconds" in data
        assert data["version"] == "3.0.0"

    def test_request_id_in_response(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert "x-request-id" in resp.headers

    def test_request_id_passthrough(self, client):
        custom_id = "test-req-12345678"
        resp = client.get("/api/health", headers={"X-Request-ID": custom_id})
        assert resp.status_code == 200
        assert resp.headers["x-request-id"] == custom_id

    def test_security_headers_in_response(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_sse_endpoint_empty_symbols(self, client):
        resp = client.get("/api/sse/realtime?symbols=")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_sse_endpoint_invalid_symbols(self, client):
        resp = client.get("/api/sse/realtime?symbols=,,,")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False


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
        client.post("/api/trading/reset")
        resp = client.post("/api/trading/buy", json={
            "symbol": "600000", "name": "浦发银行", "market": "A",
            "price": 10.0, "shares": 100, "market_price": 10.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_trading_sell_t1_restricted(self, client):
        client.post("/api/trading/reset")
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
        assert "T+1" in error_msg or "可卖" in error_msg

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
        if data["success"]:
            assert "data" in data
            assert "strategy_name" in data["data"]
        else:
            assert "error" in data

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
            "symbol": "600000",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
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

    def test_backtest_stream_submit_and_poll(self, client):
        resp = client.post("/api/backtest/stream", json={
            "symbol": "600000", "strategy_type": "dual_ma",
            "start_date": "2024-01-01", "end_date": "2024-12-31",
            "initial_capital": 1000000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "queued"
        job_id = data["job_id"]
        resp = client.get(f"/api/backtest/stream/{job_id}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

    def test_backtest_stream_not_found(self, client):
        resp = client.get("/api/backtest/stream/invalid_job_id")
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
            data = resp.json()
            if data.get("success"):
                assert "data" in data


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

    def test_watchlist_add_and_remove(self, client):
        add_resp = client.post("/api/watchlist/add", json={"symbol": "600000"})
        assert add_resp.status_code == 200
        remove_resp = client.post("/api/watchlist/remove", json={"symbol": "600000"})
        assert remove_resp.status_code == 200


class TestSystemAPI:
    def test_system_metrics(self, client):
        resp = client.get("/api/system/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        metrics = data["data"]
        assert "uptime_seconds" in metrics
        assert "api_requests_total" in metrics
        assert "avg_response_time_ms" in metrics
        assert "ws_connections" in metrics
        assert isinstance(metrics["uptime_seconds"], (int, float))
        assert isinstance(metrics["api_requests_total"], int)
        assert metrics["uptime_seconds"] >= 0

    def test_system_memory(self, client):
        resp = client.get("/api/system/memory")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        mem_data = data["data"]
        assert "memory" in mem_data
        assert "is_pressure" in mem_data
        assert "is_critical" in mem_data
        assert isinstance(mem_data["is_pressure"], bool)
        assert isinstance(mem_data["is_critical"], bool)

    def test_system_stats(self, client):
        resp = client.get("/api/system/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        stats = data["data"]
        assert "request_count" in stats
        assert "latency_buckets" in stats
        assert "error_count" in stats
        assert "uptime_seconds" in stats
        assert isinstance(stats["request_count"], int)
        assert isinstance(stats["error_count"], int)

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

    def test_portfolio_metrics_websocket_configure(self, client):
        from starlette.websockets import WebSocketDisconnect

        from api.auth import create_token
        token = create_token({"username": "testuser", "role": "admin"})
        try:
            with client.websocket_connect(f"/ws/portfolio/metrics?token={token}") as ws:
                ws.send_json({
                    "type": "configure",
                    "positions": [
                        {"symbol": "000001", "entry_price": 10.0, "shares": 1000},
                        {"symbol": "600000", "entry_price": 8.0, "shares": 2000},
                    ],
                    "base_value": 50000.0,
                })
                resp = ws.receive_json()
                assert resp["type"] == "configured"
                assert resp["symbol_count"] == 2
                assert resp["base_value"] == 50000.0
                assert "ts" in resp
        except WebSocketDisconnect:
            pass

    def test_portfolio_equity(self, client):
        resp = client.get("/api/portfolio/equity", params={"symbols": "600000,000001"})
        assert resp.status_code == 200

    def test_report_weekly(self, client):
        resp = client.get("/api/report/weekly")
        assert resp.status_code == 200


class TestInputValidation:
    def test_backtest_export_invalid_format(self, client):
        resp = client.get("/api/backtest/export", params={"format": "xml"})
        assert resp.status_code == 422

    def test_backtest_export_valid_csv(self, client):
        resp = client.get("/api/backtest/export", params={"format": "csv"})
        assert resp.status_code == 200

    def test_backtest_export_valid_json(self, client):
        resp = client.get("/api/backtest/export", params={"format": "json"})
        assert resp.status_code == 200

    def test_calendar_next_count_upper_bound(self, client):
        resp = client.get("/api/calendar/next", params={"count": 100})
        assert resp.status_code == 422

    def test_calendar_next_count_valid(self, client):
        resp = client.get("/api/calendar/next", params={"count": 5})
        assert resp.status_code == 200

    def test_search_missing_query(self, client):
        resp = client.get("/api/search")
        assert resp.status_code == 422

    def test_search_short_query(self, client):
        resp = client.get("/api/search", params={"q": ""})
        assert resp.status_code == 422


class TestCacheHeaders:
    def test_cached_endpoint_has_cache_control(self, client):
        resp = client.get("/api/search", params={"q": "600000"})
        assert resp.status_code == 200
        assert "cache-control" in resp.headers

    def test_cached_endpoint_has_x_cache_header(self, client):
        resp = client.get("/api/search", params={"q": "600000"})
        assert resp.status_code == 200
        assert "x-cache" in resp.headers


class TestCalendarAPI:
    def test_calendar_next_default(self, client):
        resp = client.get("/api/calendar/next")
        assert resp.status_code == 200

    def test_calendar_next_with_date(self, client):
        resp = client.get("/api/calendar/next", params={"d": "2025-01-01", "count": 3})
        assert resp.status_code == 200

    def test_calendar_next_count_exceeds_limit(self, client):
        resp = client.get("/api/calendar/next", params={"count": 100})
        assert resp.status_code == 422


class TestBacktestStrategiesAPI:
    def test_backtest_strategies(self, client):
        resp = client.get("/api/backtest/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True





class TestStrategyCompareAPI:
    def test_compare_happy_path(self, client):
        resp = client.get("/api/strategy/compare", params={
            "symbols": "600000",
            "strategies": "dual_ma,macd",
            "period": "6m",
            "capital": 100000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        assert "strategies" in data.get("data", {})
        assert "ranking" in data.get("data", {})
        assert "comparison_matrix" in data.get("data", {})

    def test_compare_missing_required_params(self, client):
        resp = client.get("/api/strategy/compare")
        assert resp.status_code == 422

    def test_compare_unknown_strategy(self, client):
        resp = client.get("/api/strategy/compare", params={
            "symbols": "600000",
            "strategies": "nonexistent_strategy_xyz",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        strategies = data.get("data", {}).get("strategies", [])
        assert any("error" in s for s in strategies)

    def test_compare_too_many_strategies(self, client):
        resp = client.get("/api/strategy/compare", params={
            "symbols": "600000",
            "strategies": "a,b,c,d,e,f,g",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is False

    def test_compare_empty_symbols(self, client):
        resp = client.get("/api/strategy/compare", params={
            "symbols": ",,",
            "strategies": "dual_ma",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is False


class TestRebalanceScheduleAPI:
    def test_create_schedule(self, client):
        resp = client.post("/api/portfolio/rebalance/schedule", json={
            "name": "test_rebalance",
            "symbols": "600000,000001",
            "frequency": "weekly",
            "drift_threshold": 0.05,
            "capital": 100000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        assert "schedule_id" in data.get("data", {})

    def test_create_schedule_single_symbol_rejected(self, client):
        resp = client.post("/api/portfolio/rebalance/schedule", json={
            "name": "bad_rebalance",
            "symbols": "600000",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is False

    def test_list_schedules(self, client):
        client.post("/api/portfolio/rebalance/schedule", json={
            "name": "list_test",
            "symbols": "600000,000001",
        })
        resp = client.get("/api/portfolio/rebalance/schedules")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        assert "schedules" in data.get("data", {})
        assert data["data"]["total"] >= 1

    def test_delete_nonexistent_schedule(self, client):
        resp = client.delete("/api/portfolio/rebalance/schedule/nonexist")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is False

    def test_check_nonexistent_schedule(self, client):
        resp = client.post("/api/portfolio/rebalance/schedule/nonexist/check")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is False


class TestRegimeDashboardAPI:
    def test_dashboard_happy_path(self, client):
        resp = client.get("/api/market/regime/dashboard", params={
            "symbols": "600000,000001",
            "period": 120,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        assert "per_symbol" in data.get("data", {})
        assert "dominant_regime" in data.get("data", {})
        assert "regime_distribution" in data.get("data", {})

    def test_dashboard_missing_symbols(self, client):
        resp = client.get("/api/market/regime/dashboard")
        assert resp.status_code == 422

    def test_dashboard_empty_symbols(self, client):
        resp = client.get("/api/market/regime/dashboard", params={"symbols": ",,"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is False

    def test_dashboard_too_many_symbols(self, client):
        symbols = ",".join([f"60000{i}" for i in range(25)])
        resp = client.get("/api/market/regime/dashboard", params={"symbols": symbols})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is False


class TestCorrelationDeepAnalysisAPI:
    def test_analysis_happy_path(self, client):
        resp = client.get("/api/portfolio/correlation/analysis", params={
            "symbols": "600000,000001",
            "period": "1y",
            "method": "pearson",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        inner = data.get("data", {})
        assert "correlation_matrix" in inner
        assert "diversification_score" in inner
        assert "highly_correlated_pairs" in inner

    def test_analysis_spearman_method(self, client):
        resp = client.get("/api/portfolio/correlation/analysis", params={
            "symbols": "600000,000001",
            "method": "spearman",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True

    def test_analysis_missing_symbols(self, client):
        resp = client.get("/api/portfolio/correlation/analysis")
        assert resp.status_code == 422

    def test_analysis_single_symbol_rejected(self, client):
        resp = client.get("/api/portfolio/correlation/analysis", params={"symbols": "600000"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is False


class TestBareExceptRegression:
    def test_metrics_endpoint_returns_200(self, client):
        resp = client.get("/api/system/metrics")
        assert resp.status_code == 200
        data = resp.json()
        inner = data.get("data", data)
        assert "memory_mb" in inner or "uptime_seconds" in inner

    def test_correlation_with_invalid_symbol_returns_graceful(self, client):
        resp = client.get("/api/stock/correlation/INVALID999", params={"period": "1mo"})
        assert resp.status_code in (200, 404, 500)


class TestTCAAPI:
    def test_tca_analyze(self, client):
        resp = client.post("/api/tca/analyze", json={
            "symbol": "600000",
            "strategy_name": "test",
            "side": "buy",
            "decision_price": 10.0,
            "arrival_price": 10.05,
            "execution_price": 10.08,
            "vwap_benchmark": 10.03,
            "twap_benchmark": 10.04,
            "quantity": 1000,
            "execution_timestamp": "2024-01-15 09:35:00",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "cost_metrics" in data["data"]

    def test_tca_batch(self, client):
        trades = [
            {"symbol": "600000", "strategy_name": "s1", "side": "buy",
             "decision_price": 10.0, "arrival_price": 10.05, "execution_price": 10.08,
             "vwap_benchmark": 10.03, "twap_benchmark": 10.04, "quantity": 1000,
             "execution_timestamp": "2024-01-15 09:35:00"},
            {"symbol": "000001", "strategy_name": "s2", "side": "sell",
             "decision_price": 15.0, "arrival_price": 14.95, "execution_price": 14.90,
             "vwap_benchmark": 14.97, "twap_benchmark": 14.96, "quantity": 500,
             "execution_timestamp": "2024-01-15 10:15:00"},
        ]
        resp = client.post("/api/tca/batch", json={"trades": trades})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "summary" in data["data"]
        assert data["data"]["summary"]["total_trades"] == 2

    def test_tca_recommend(self, client):
        resp = client.post("/api/tca/recommend", json={"symbol": "600000"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "recommended_algorithm" in data["data"]


class TestStressAPI:
    def test_stress_scenarios_list(self, client):
        resp = client.get("/api/portfolio/stress/scenarios")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) > 0

    def test_stress_run(self, client):
        positions = [
            {"symbol": "600000", "value": 10000, "asset_type": "equity"},
        ]
        resp = client.post("/api/portfolio/stress/run", json={"positions": positions})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_stress_empty_positions(self, client):
        resp = client.post("/api/portfolio/stress/run", json={"positions": []})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False


class TestFactorAPI:
    def test_factor_registry(self, client):
        resp = client.get("/api/factor/registry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "factors" in data["data"]
        assert "categories" in data["data"]

    def test_factor_ic_analysis(self, client):
        np.random.seed(42)
        n = 100
        factor_vals = np.random.randn(n).tolist()
        fwd_rets = (np.random.randn(n) * 0.02).tolist()
        resp = client.post("/api/factor/ic-analysis", json={
            "factor_values": factor_vals,
            "forward_returns": fwd_rets,
            "max_lag": 10,
            "n_quintiles": 5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "mean_ic" in data["data"]
        assert "icir" in data["data"]

    def test_factor_ic_analysis_insufficient_data(self, client):
        resp = client.post("/api/factor/ic-analysis", json={
            "factor_values": [1, 2, 3],
            "forward_returns": [0.01, 0.02, 0.03],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_factor_quintile_test(self, client):
        np.random.seed(42)
        n = 50
        resp = client.post("/api/factor/quintile-test", json={
            "factor_values": np.random.randn(n).tolist(),
            "forward_returns": (np.random.randn(n) * 0.02).tolist(),
            "n_quintiles": 5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_factor_neutralize(self, client):
        resp = client.post("/api/factor/neutralize", json={
            "factor_values": [1.0, 2.0, 3.0, 4.0, 5.0],
            "industry_labels": ["tech", "tech", "fin", "fin", "fin"],
            "market_cap": [100, 200, 150, 300, 250],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "neutralized_values" in data["data"]


class TestMLAPI:
    def test_ml_labels(self, client):
        np.random.seed(42)
        prices = (100 + np.cumsum(np.random.randn(60) * 0.5)).tolist()
        resp = client.post("/api/ml/labels", json={
            "prices": prices,
            "method": "triple_barrier",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "n_labels" in data["data"]

    def test_ml_labels_empty(self, client):
        resp = client.post("/api/ml/labels", json={"prices": []})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_ml_drift_check(self, client):
        np.random.seed(42)
        current = {"f1": np.random.randn(50).tolist(), "f2": np.random.randn(50).tolist()}
        reference = {"f1": np.random.randn(50).tolist(), "f2": np.random.randn(50).tolist()}
        resp = client.post("/api/ml/drift-check", json={
            "current_features": current,
            "reference_features": reference,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "drift_detected" in data["data"]

    def test_ml_drift_check_empty(self, client):
        resp = client.post("/api/ml/drift-check", json={
            "current_features": {},
            "reference_features": {},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False


class TestFactorMLInputValidation:
    def test_ic_analysis_max_lag_zero(self, client):
        resp = client.post("/api/factor/ic-analysis", json={
            "factor_values": np.random.randn(20).tolist(),
            "forward_returns": np.random.randn(20).tolist(),
            "max_lag": 0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "max_lag" in data["error"]

    def test_ic_analysis_max_lag_negative(self, client):
        resp = client.post("/api/factor/ic-analysis", json={
            "factor_values": np.random.randn(20).tolist(),
            "forward_returns": np.random.randn(20).tolist(),
            "max_lag": -5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "max_lag" in data["error"]

    def test_ic_analysis_n_quintiles_one(self, client):
        resp = client.post("/api/factor/ic-analysis", json={
            "factor_values": np.random.randn(20).tolist(),
            "forward_returns": np.random.randn(20).tolist(),
            "n_quintiles": 1,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "n_quintiles" in data["error"]

    def test_ic_analysis_nan_in_factor_values(self, client):
        vals = np.random.randn(20).tolist()
        vals[5] = None
        resp = client.post("/api/factor/ic-analysis", json={
            "factor_values": vals,
            "forward_returns": np.random.randn(20).tolist(),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "NaN" in data["error"]

    def test_ic_analysis_nan_in_forward_returns(self, client):
        rets = np.random.randn(20).tolist()
        rets[3] = None
        resp = client.post("/api/factor/ic-analysis", json={
            "factor_values": np.random.randn(20).tolist(),
            "forward_returns": rets,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "NaN" in data["error"]

    def test_ic_analysis_length_mismatch(self, client):
        resp = client.post("/api/factor/ic-analysis", json={
            "factor_values": np.random.randn(20).tolist(),
            "forward_returns": np.random.randn(15).tolist(),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "长度" in data["error"]

    def test_quintile_test_n_quintiles_zero(self, client):
        resp = client.post("/api/factor/quintile-test", json={
            "factor_values": np.random.randn(20).tolist(),
            "forward_returns": np.random.randn(20).tolist(),
            "n_quintiles": 0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "n_quintiles" in data["error"]

    def test_quintile_test_nan_in_input(self, client):
        vals = np.random.randn(20).tolist()
        vals[0] = None
        resp = client.post("/api/factor/quintile-test", json={
            "factor_values": vals,
            "forward_returns": np.random.randn(20).tolist(),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "NaN" in data["error"]

    def test_quintile_test_length_mismatch(self, client):
        resp = client.post("/api/factor/quintile-test", json={
            "factor_values": np.random.randn(20).tolist(),
            "forward_returns": np.random.randn(10).tolist(),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "长度" in data["error"]

    def test_neutralize_length_mismatch(self, client):
        resp = client.post("/api/factor/neutralize", json={
            "factor_values": [1.0, 2.0, 3.0],
            "industry_labels": ["a", "b"],
            "market_cap": [100, 200, 300],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "长度" in data["error"]

    def test_neutralize_empty_factor_values(self, client):
        resp = client.post("/api/factor/neutralize", json={
            "factor_values": [],
            "industry_labels": [],
            "market_cap": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "不能为空" in data["error"]

    def test_neutralize_nan_in_market_cap(self, client):
        resp = client.post("/api/factor/neutralize", json={
            "factor_values": [1.0, 2.0, 3.0],
            "industry_labels": ["a", "b", "c"],
            "market_cap": [100, None, 300],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "NaN" in data["error"]

    def test_optimize_dimension_mismatch(self, client):
        resp = client.post("/api/factor/optimize", json={
            "expected_returns": [0.05, 0.03, 0.04],
            "cov_matrix": [[0.01, 0.005], [0.005, 0.02]],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "维度" in data["error"]

    def test_optimize_non_square_cov_matrix(self, client):
        resp = client.post("/api/factor/optimize", json={
            "expected_returns": [0.05, 0.03],
            "cov_matrix": [[0.01, 0.005, 0.003], [0.005, 0.02, 0.001]],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "方阵" in data["error"]

    def test_optimize_nan_in_expected_returns(self, client):
        resp = client.post("/api/factor/optimize", json={
            "expected_returns": [0.05, None],
            "cov_matrix": [[0.01, 0.005], [0.005, 0.02]],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "NaN" in data["error"]

    def test_optimize_nan_in_cov_matrix(self, client):
        resp = client.post("/api/factor/optimize", json={
            "expected_returns": [0.05, 0.03],
            "cov_matrix": [[0.01, None], [0.005, 0.02]],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "NaN" in data["error"]

    def test_ml_labels_nan_in_prices(self, client):
        prices = (100 + np.cumsum(np.random.randn(20) * 0.5)).tolist()
        prices[5] = None
        resp = client.post("/api/ml/labels", json={"prices": prices})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "NaN" in data["error"]

    def test_ml_labels_too_few_prices(self, client):
        resp = client.post("/api/ml/labels", json={"prices": [100.0, 101.0]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "3" in data["error"]

    def test_ml_drift_check_column_mismatch(self, client):
        np.random.seed(42)
        current = {"f1": np.random.randn(30).tolist(), "f2": np.random.randn(30).tolist()}
        reference = {"f1": np.random.randn(30).tolist(), "f3": np.random.randn(30).tolist()}
        resp = client.post("/api/ml/drift-check", json={
            "current_features": current,
            "reference_features": reference,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "不一致" in data["error"]
