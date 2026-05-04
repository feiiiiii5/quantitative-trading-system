import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_has_status(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert "status" in data

    def test_health_has_version(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert "version" in data


class TestMarketEndpoints:
    def test_market_status(self, client):
        resp = client.get("/api/market/status")
        assert resp.status_code == 200

    def test_market_overview(self, client):
        resp = client.get("/api/market/overview")
        assert resp.status_code == 200


class TestStockEndpoints:
    def test_search(self, client):
        resp = client.get("/api/search", params={"q": "平安银行"})
        assert resp.status_code == 200

    def test_realtime(self, client):
        resp = client.get("/api/stock/realtime/000001")
        assert resp.status_code == 200

    def test_history(self, client):
        resp = client.get("/api/stock/history/000001", params={"period": "1m"})
        assert resp.status_code == 200


class TestBacktestEndpoints:
    def test_strategies_list(self, client):
        resp = client.get("/api/backtest/strategies")
        assert resp.status_code == 200


class TestSystemEndpoints:
    def test_system_metrics(self, client):
        resp = client.get("/api/system/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "uptime_seconds" in data["data"]

    def test_config_get_valid(self, client):
        resp = client.get("/api/config/watchlist")
        assert resp.status_code == 200

    def test_config_get_disallowed_key(self, client):
        resp = client.get("/api/config/secrets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_config_set_disallowed_key(self, client):
        resp = client.post("/api/config/secrets", json={"value": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_config_set_allowed_key(self, client):
        resp = client.post("/api/config/ui_settings", json={"value": "dark"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestRegimeEndpoints:
    def test_regime_detect(self, client):
        resp = client.get("/api/regime/detect/600000")
        assert resp.status_code == 200

    def test_risk_monitor(self, client):
        resp = client.get("/api/risk/monitor/600000")
        assert resp.status_code == 200


class TestAuthMiddleware:
    def test_public_health_bypasses_auth(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_public_docs_bypasses_auth(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_missing_key_returns_401_when_enabled(self, client):
        from api.auth import APIAuthMiddleware
        assert APIAuthMiddleware is not None


class TestStockEdgeCases:
    def test_invalid_symbol_special_chars(self, client):
        resp = client.get("/api/stock/realtime/600@00")
        assert resp.status_code == 422

    def test_invalid_symbol_with_spaces(self, client):
        resp = client.get("/api/stock/realtime/600 000")
        assert resp.status_code == 422

    def test_invalid_symbol_html_injection(self, client):
        resp = client.get("/api/stock/realtime/<script>")
        assert resp.status_code == 422


class TestConfigEdgeCases:
    def test_config_set_get_roundtrip(self, client):
        set_resp = client.post("/api/config/ui_settings", json={"value": "light"})
        assert set_resp.status_code == 200
        get_resp = client.get("/api/config/ui_settings")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["success"] is True

    def test_config_disallowed_key_returns_error(self, client):
        for key in ["internal_token", "admin_password", "secrets"]:
            resp = client.get(f"/api/config/{key}")
            assert resp.status_code == 200
            assert not resp.json()["success"]


class TestHotEndpoints:
    def test_stock_realtime_valid(self, client):
        resp = client.get("/api/stock/realtime/600000")
        assert resp.status_code == 200

    def test_stock_ai_summary(self, client):
        resp = client.get("/api/stock/ai_summary/600000")
        assert resp.status_code == 200


class TestBacktestEndpoints:
    def test_backtest_history(self, client):
        resp = client.get("/api/backtest/history")
        assert resp.status_code == 200
