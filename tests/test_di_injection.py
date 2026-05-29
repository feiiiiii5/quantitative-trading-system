from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import FetcherDep, get_fetcher
from core.data_fetcher import SmartDataFetcher


@pytest.fixture
def mock_fetcher():
    fetcher = MagicMock(spec=SmartDataFetcher)
    fetcher.get_market_overview = AsyncMock(return_value={
        "indices": {"sh000001": {"price": 3200, "change_pct": 1.5}},
        "market_breadth": {"up": 2000, "down": 1500, "flat": 500},
        "timestamp": 1700000000,
    })
    fetcher.get_realtime = AsyncMock(return_value={
        "price": 100.0,
        "change_pct": 2.5,
        "volume": 50000,
        "bid_prices": [99.9],
        "bid_volumes": [100],
        "ask_prices": [100.1],
        "ask_volumes": [200],
        "has_depth": True,
    })
    fetcher.get_history = AsyncMock(return_value=MagicMock(
        __len__=lambda self: 100,
        __getitem__=lambda self, idx: MagicMock(),
        columns=["close", "volume"],
    ))
    fetcher.get_fundamentals = AsyncMock(return_value={"行业": "银行", "pe": 5.5})
    return fetcher


def test_di_override_market_overview(mock_fetcher):
    from api.routers.market import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_fetcher] = lambda: mock_fetcher

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/market/overview")

    assert resp.status_code == 200
    mock_fetcher.get_market_overview.assert_awaited_once()


def test_di_override_stock_realtime(mock_fetcher):
    from api.routers.stock import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_fetcher] = lambda: mock_fetcher

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/stock/realtime/600519")

    assert resp.status_code == 200
    mock_fetcher.get_realtime.assert_awaited()


def test_di_override_perf_sector_heatmap(mock_fetcher):
    from api.perf_routes import perf_router

    app = FastAPI()
    app.include_router(perf_router, prefix="/api")
    app.dependency_overrides[get_fetcher] = lambda: mock_fetcher

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/market/heatmap")

    assert resp.status_code == 200


def test_di_no_override_returns_error():
    from api.routers.market import router

    app = FastAPI()
    app.include_router(router, prefix="/api")

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/market/overview")

    assert resp.status_code == 500
