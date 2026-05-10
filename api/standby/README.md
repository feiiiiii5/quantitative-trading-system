# Standby API 模块

前端系统当前未使用的后端模块。保留供未来扩展。

| 模块 | 路由前缀 | 功能说明 |
|------|----------|----------|
| feature_routes.py | /api | 特征工程、技术指标计算 |
| duckdb_routes.py | /api | DuckDB 数据库查询接口 |

## 启用方式

在 main.py 中取消注释对应的 include_router 即可启用。
