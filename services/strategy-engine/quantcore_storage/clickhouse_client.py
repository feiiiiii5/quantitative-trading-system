import logging
from typing import Any

import clickhouse_connect
import pandas as pd
from clickhouse_connect.driver.client import Client as ChClient

logger = logging.getLogger(__name__)

_TICKS_TABLE = "ticks"
_BARS_TABLE = "bars"
_ORDERBOOK_SNAPSHOTS_TABLE = "orderbook_snapshots"
_TRADES_TABLE = "trades"
_BACKTEST_RESULTS_TABLE = "backtest_results"


class ClickHouseClient:
    def __init__(
        self,
        host: str = "clickhouse",
        port: int = 8123,
        database: str = "quantcore",
        username: str = "default",
        password: str = "",
    ) -> None:
        self._database = database
        self._client: ChClient = clickhouse_connect.get_client(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
        )
        logger.info(
            "ClickHouseClient initialized: host=%s port=%d database=%s",
            host,
            port,
            database,
        )

    def insert_ticks(self, ticks: list[dict[str, Any]]) -> int:
        if not ticks:
            return 0
        columns = [
            "symbol", "timestamp", "bid_price", "ask_price",
            "bid_size", "ask_size", "last_price", "last_size",
        ]
        rows = [
            [
                t.get("symbol", ""),
                t.get("timestamp"),
                t.get("bid_price", 0.0),
                t.get("ask_price", 0.0),
                t.get("bid_size", 0),
                t.get("ask_size", 0),
                t.get("last_price", 0.0),
                t.get("last_size", 0),
            ]
            for t in ticks
        ]
        self._client.insert(_TICKS_TABLE, rows, column_names=columns)
        logger.info("Inserted %d tick records", len(rows))
        return len(rows)

    def insert_bars(self, bars: list[dict[str, Any]]) -> int:
        if not bars:
            return 0
        columns = [
            "symbol", "timestamp", "open", "high", "low", "close",
            "volume", "vwap", "trade_count",
        ]
        rows = [
            [
                b.get("symbol", ""),
                b.get("timestamp"),
                b.get("open", 0.0),
                b.get("high", 0.0),
                b.get("low", 0.0),
                b.get("close", 0.0),
                b.get("volume", 0),
                b.get("vwap", 0.0),
                b.get("trade_count", 0),
            ]
            for b in bars
        ]
        self._client.insert(_BARS_TABLE, rows, column_names=columns)
        logger.info("Inserted %d bar records", len(rows))
        return len(rows)

    def insert_order_book_snapshots(self, snapshots: list[dict[str, Any]]) -> int:
        if not snapshots:
            return 0
        columns = [
            "symbol", "timestamp", "num_levels", "bid_prices",
            "bid_sizes", "ask_prices", "ask_sizes",
        ]
        rows = [
            [
                s.get("symbol", ""),
                s.get("timestamp"),
                s.get("num_levels", 0),
                s.get("bid_prices", []),
                s.get("bid_sizes", []),
                s.get("ask_prices", []),
                s.get("ask_sizes", []),
            ]
            for s in snapshots
        ]
        self._client.insert(_ORDERBOOK_SNAPSHOTS_TABLE, rows, column_names=columns)
        logger.info("Inserted %d order book snapshot records", len(rows))
        return len(rows)

    def query_ticks(
        self,
        symbol: str,
        start: str,
        end: str,
        limit: int = 10000,
    ) -> pd.DataFrame:
        result = self._client.query_df(
            """
            SELECT symbol, timestamp, bid_price, ask_price,
                   bid_size, ask_size, last_price, last_size
            FROM ticks
            WHERE symbol = %(symbol)s
              AND timestamp >= %(start)s
              AND timestamp < %(end)s
            ORDER BY timestamp
            LIMIT %(limit)s
            """,
            parameters={
                "symbol": symbol,
                "start": start,
                "end": end,
                "limit": limit,
            },
        )
        logger.info(
            "Queried ticks: symbol=%s range=[%s, %s) rows=%d",
            symbol,
            start,
            end,
            len(result),
        )
        return result

    def query_bars(
        self,
        symbol: str,
        start: str,
        end: str,
        period: str = "1m",
    ) -> pd.DataFrame:
        result = self._client.query_df(
            """
            SELECT symbol, timestamp, open, high, low, close,
                   volume, vwap, trade_count
            FROM bars
            WHERE symbol = %(symbol)s
              AND timestamp >= %(start)s
              AND timestamp < %(end)s
            ORDER BY timestamp
            """,
            parameters={
                "symbol": symbol,
                "start": start,
                "end": end,
            },
        )
        logger.info(
            "Queried bars: symbol=%s period=%s range=[%s, %s) rows=%d",
            symbol,
            period,
            start,
            end,
            len(result),
        )
        return result

    def query_aggregated(
        self,
        symbol: str,
        start: str,
        end: str,
        agg: str = "5m",
    ) -> pd.DataFrame:
        result = self._client.query_df(
            """
            SELECT
                symbol,
                toStartOfInterval(timestamp, INTERVAL %(agg)s Minute) AS period_start,
                argMin(open, timestamp) AS open,
                max(high) AS high,
                min(low) AS low,
                argMax(close, timestamp) AS close,
                sum(volume) AS volume,
                sum(last_size * last_price) / nullIf(sum(last_size), 0) AS vwap,
                count() AS trade_count
            FROM ticks
            WHERE symbol = %(symbol)s
              AND timestamp >= %(start)s
              AND timestamp < %(end)s
            GROUP BY symbol, period_start
            ORDER BY period_start
            """,
            parameters={
                "symbol": symbol,
                "start": start,
                "end": end,
                "agg": agg,
            },
        )
        logger.info(
            "Queried aggregated ticks: symbol=%s agg=%s range=[%s, %s) rows=%d",
            symbol,
            agg,
            start,
            end,
            len(result),
        )
        return result

    def create_tables(self) -> None:
        self._client.command("""
            CREATE TABLE IF NOT EXISTS ticks (
                symbol String,
                timestamp DateTime64(3),
                bid_price Float64,
                ask_price Float64,
                bid_size Int64,
                ask_size Int64,
                last_price Float64,
                last_size Int64
            )
            ENGINE = MergeTree()
            PARTITION BY toYYYYMM(timestamp)
            ORDER BY (symbol, timestamp)
            TTL timestamp + INTERVAL 90 DAY
        """)
        logger.info("Ensured table 'ticks' exists")

        self._client.command("""
            CREATE TABLE IF NOT EXISTS bars (
                symbol String,
                timestamp DateTime64(3),
                open Float64,
                high Float64,
                low Float64,
                close Float64,
                volume Int64,
                vwap Float64,
                trade_count Int64
            )
            ENGINE = MergeTree()
            PARTITION BY toYYYYMM(timestamp)
            ORDER BY (symbol, timestamp)
            TTL timestamp + INTERVAL 365 DAY
        """)
        logger.info("Ensured table 'bars' exists")

        self._client.command("""
            CREATE TABLE IF NOT EXISTS orderbook_snapshots (
                symbol String,
                timestamp DateTime64(3),
                num_levels Int32,
                bid_prices Array(Float64),
                bid_sizes Array(Int64),
                ask_prices Array(Float64),
                ask_sizes Array(Int64)
            )
            ENGINE = MergeTree()
            PARTITION BY toYYYYMM(timestamp)
            ORDER BY (symbol, timestamp)
            TTL timestamp + INTERVAL 30 DAY
        """)
        logger.info("Ensured table 'orderbook_snapshots' exists")

        self._client.command("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id String,
                symbol String,
                timestamp DateTime64(3),
                side String,
                quantity Int64,
                price Float64,
                commission Float64,
                account_id String,
                strategy_id String
            )
            ENGINE = MergeTree()
            PARTITION BY toYYYYMM(timestamp)
            ORDER BY (symbol, timestamp)
            TTL timestamp + INTERVAL 365 DAY
        """)
        logger.info("Ensured table 'trades' exists")

        self._client.command("""
            CREATE TABLE IF NOT EXISTS backtest_results (
                backtest_id String,
                strategy_id String,
                timestamp DateTime64(3),
                total_return Float64,
                sharpe_ratio Float64,
                max_drawdown Float64,
                win_rate Float64,
                profit_factor Float64,
                total_trades Int64,
                parameters String
            )
            ENGINE = MergeTree()
            ORDER BY (strategy_id, timestamp)
        """)
        logger.info("Ensured table 'backtest_results' exists")

    def get_table_stats(self, table: str) -> dict[str, Any]:
        allowed_tables = {
            _TICKS_TABLE, _BARS_TABLE, _ORDERBOOK_SNAPSHOTS_TABLE,
            _TRADES_TABLE, _BACKTEST_RESULTS_TABLE,
        }
        if table not in allowed_tables:
            logger.warning("Stats requested for unknown table: %s", table)
            return {"error": f"unknown table: {table}"}

        row_count_result = self._client.command(
            "SELECT count() FROM {table:Identifier}",
            parameters={"table": table},
        )
        size_result = self._client.command(
            """
            SELECT formatReadableSize(sum(bytes_on_disk))
            FROM system.parts
            WHERE database = %(database)s AND table = %(table)s AND active
            """,
            parameters={"database": self._database, "table": table},
        )
        date_range_result = self._client.query_row(
            """
            SELECT min(timestamp), max(timestamp)
            FROM {table:Identifier}
            """,
            parameters={"table": table},
        )
        return {
            "table": table,
            "row_count": row_count_result,
            "size_on_disk": size_result if size_result else "0 B",
            "date_range": {
                "min": str(date_range_result[0]) if date_range_result and date_range_result[0] else None,
                "max": str(date_range_result[1]) if date_range_result and date_range_result[1] else None,
            },
        }
