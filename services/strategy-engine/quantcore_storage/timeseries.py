import logging
from typing import Any

import pandas as pd

from quantcore_storage.clickhouse_client import ClickHouseClient

logger = logging.getLogger(__name__)

_EQUITY_CURVE_TABLE = "equity_curve"
_RISK_METRICS_TABLE = "risk_metrics"
_TRADE_JOURNAL_TABLE = "trade_journal"


class TimeSeriesStore:
    def __init__(self, client: ClickHouseClient) -> None:
        self._client = client
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        ch = self._client._client

        ch.command("""
            CREATE TABLE IF NOT EXISTS equity_curve (
                backtest_id String,
                timestamp DateTime64(3),
                equity Float64,
                drawdown Float64,
                pnl Float64
            )
            ENGINE = MergeTree()
            PARTITION BY toYYYYMM(timestamp)
            ORDER BY (backtest_id, timestamp)
            TTL timestamp + INTERVAL 365 DAY
        """)
        logger.info("Ensured table 'equity_curve' exists")

        ch.command("""
            CREATE TABLE IF NOT EXISTS risk_metrics (
                account_id String,
                timestamp DateTime64(3),
                var_95 Float64,
                var_99 Float64,
                cvar_95 Float64,
                max_drawdown Float64,
                sharpe_ratio Float64,
                sortino_ratio Float64,
                volatility Float64,
                beta Float64
            )
            ENGINE = MergeTree()
            PARTITION BY toYYYYMM(timestamp)
            ORDER BY (account_id, timestamp)
            TTL timestamp + INTERVAL 365 DAY
        """)
        logger.info("Ensured table 'risk_metrics' exists")

        ch.command("""
            CREATE TABLE IF NOT EXISTS trade_journal (
                account_id String,
                timestamp DateTime64(3),
                symbol String,
                side String,
                quantity Int64,
                entry_price Float64,
                exit_price Float64,
                pnl Float64,
                commission Float64,
                strategy_id String,
                notes String
            )
            ENGINE = MergeTree()
            PARTITION BY toYYYYMM(timestamp)
            ORDER BY (account_id, timestamp)
            TTL timestamp + INTERVAL 365 DAY
        """)
        logger.info("Ensured table 'trade_journal' exists")

    def write_equity_curve(
        self,
        backtest_id: str,
        points: list[dict[str, Any]],
    ) -> int:
        if not points:
            return 0
        columns = ["backtest_id", "timestamp", "equity", "drawdown", "pnl"]
        rows = [
            [
                backtest_id,
                p.get("timestamp"),
                p.get("equity", 0.0),
                p.get("drawdown", 0.0),
                p.get("pnl", 0.0),
            ]
            for p in points
        ]
        self._client._client.insert(_EQUITY_CURVE_TABLE, rows, column_names=columns)
        logger.info(
            "Wrote equity curve: backtest_id=%s points=%d",
            backtest_id,
            len(rows),
        )
        return len(rows)

    def read_equity_curve(self, backtest_id: str) -> pd.DataFrame:
        result = self._client._client.query_df(
            """
            SELECT backtest_id, timestamp, equity, drawdown, pnl
            FROM equity_curve
            WHERE backtest_id = %(backtest_id)s
            ORDER BY timestamp
            """,
            parameters={"backtest_id": backtest_id},
        )
        logger.info(
            "Read equity curve: backtest_id=%s rows=%d",
            backtest_id,
            len(result),
        )
        return result

    def write_risk_metrics(
        self,
        account_id: str,
        metrics: dict[str, Any],
    ) -> int:
        columns = [
            "account_id", "timestamp", "var_95", "var_99", "cvar_95",
            "max_drawdown", "sharpe_ratio", "sortino_ratio",
            "volatility", "beta",
        ]
        row = [
            account_id,
            metrics.get("timestamp"),
            metrics.get("var_95", 0.0),
            metrics.get("var_99", 0.0),
            metrics.get("cvar_95", 0.0),
            metrics.get("max_drawdown", 0.0),
            metrics.get("sharpe_ratio", 0.0),
            metrics.get("sortino_ratio", 0.0),
            metrics.get("volatility", 0.0),
            metrics.get("beta", 0.0),
        ]
        self._client._client.insert(_RISK_METRICS_TABLE, [row], column_names=columns)
        logger.info("Wrote risk metrics: account_id=%s", account_id)
        return 1

    def read_risk_metrics(
        self,
        account_id: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        result = self._client._client.query_df(
            """
            SELECT account_id, timestamp, var_95, var_99, cvar_95,
                   max_drawdown, sharpe_ratio, sortino_ratio,
                   volatility, beta
            FROM risk_metrics
            WHERE account_id = %(account_id)s
              AND timestamp >= %(start)s
              AND timestamp < %(end)s
            ORDER BY timestamp
            """,
            parameters={
                "account_id": account_id,
                "start": start,
                "end": end,
            },
        )
        logger.info(
            "Read risk metrics: account_id=%s range=[%s, %s) rows=%d",
            account_id,
            start,
            end,
            len(result),
        )
        return result

    def write_trade_journal(self, entry: dict[str, Any]) -> int:
        columns = [
            "account_id", "timestamp", "symbol", "side", "quantity",
            "entry_price", "exit_price", "pnl", "commission",
            "strategy_id", "notes",
        ]
        row = [
            entry.get("account_id", ""),
            entry.get("timestamp"),
            entry.get("symbol", ""),
            entry.get("side", ""),
            entry.get("quantity", 0),
            entry.get("entry_price", 0.0),
            entry.get("exit_price", 0.0),
            entry.get("pnl", 0.0),
            entry.get("commission", 0.0),
            entry.get("strategy_id", ""),
            entry.get("notes", ""),
        ]
        self._client._client.insert(_TRADE_JOURNAL_TABLE, [row], column_names=columns)
        logger.info(
            "Wrote trade journal: account_id=%s symbol=%s",
            entry.get("account_id", ""),
            entry.get("symbol", ""),
        )
        return 1

    def read_trade_journal(
        self,
        account_id: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        result = self._client._client.query_df(
            """
            SELECT account_id, timestamp, symbol, side, quantity,
                   entry_price, exit_price, pnl, commission,
                   strategy_id, notes
            FROM trade_journal
            WHERE account_id = %(account_id)s
              AND timestamp >= %(start)s
              AND timestamp < %(end)s
            ORDER BY timestamp
            """,
            parameters={
                "account_id": account_id,
                "start": start,
                "end": end,
            },
        )
        logger.info(
            "Read trade journal: account_id=%s range=[%s, %s) rows=%d",
            account_id,
            start,
            end,
            len(result),
        )
        return result

    def cleanup_before_date(self, table: str, date: str) -> int:
        allowed_tables = {
            _EQUITY_CURVE_TABLE,
            _RISK_METRICS_TABLE,
            _TRADE_JOURNAL_TABLE,
        }
        if table not in allowed_tables:
            logger.warning("Cleanup requested for unknown table: %s", table)
            return 0

        count_result = self._client._client.command(
            "SELECT count() FROM {table:Identifier} WHERE timestamp < %(date)s",
            parameters={"table": table, "date": date},
        )
        self._client._client.command(
            "ALTER TABLE {table:Identifier} DELETE WHERE timestamp < %(date)s",
            parameters={"table": table, "date": date},
        )
        logger.info(
            "Cleanup: table=%s before=%s rows_removed=%s",
            table,
            date,
            count_result,
        )
        return count_result if isinstance(count_result, int) else 0
