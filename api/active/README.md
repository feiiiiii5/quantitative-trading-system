# Active API 模块

前端系统当前正在使用的后端模块。

| 模块 | 路由前缀 | 前端页面 |
|------|----------|----------|
| routes.py | /api | Dashboard, Market, StockDetail, Portfolio, Watchlist, Trading |
| perf_routes.py | /api | Risk, Terminal, Market(K线), Cache管理, SSE事件流, WebSocket |
| backtest_routes.py | /api | Strategy(回测), Backtest(高级功能) |
| websocket_manager.py | - | WebSocket 实时推送 |

## 前端 API 调用清单

- GET /market/overview → market.ts
- GET /market/stocks → market.ts
- GET /market/heatmap → market.ts
- GET /market/kline → StockDetailPage.tsx
- GET /market/quote → StockDetailPage.tsx
- GET /search → market.ts
- GET /risk/metrics → risk.ts
- GET /strategies/list → strategy.ts
- POST /backtest/run → strategy.ts
- GET /terminal/orderbook → terminal.ts
- GET /terminal/trades → terminal.ts
- POST /ai/summary → DashboardPage.tsx
- WS /api/ws/market → websocket.ts
