__all__ = ["DuckDBAnalytics"]

"""DuckDB-powered analytical queries for portfolio analytics.

This module provides high-performance analytical capabilities using DuckDB's
SQL engine with zero-copy pandas DataFrame integration. Falls back gracefully
to pandas-based computation if DuckDB is unavailable.
"""

import logging
import re
from typing import Any

import numpy as np
import pandas as pd

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(name: str, context: str = "identifier") -> None:
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(
            "Invalid %s: %r (must match [A-Za-z_][A-Za-z0-9_]*)" % (context, name)
        )


def _validate_path(path: str) -> None:
    if ".." in path or path.startswith("/"):
        raise ValueError("Invalid path: %r (must be relative, no parent traversal)" % path)


try:
    import duckdb

    DUCKDB_AVAILABLE = True
except ImportError:
    DUCKDB_AVAILABLE = False

logger = logging.getLogger(__name__)


class DuckDBAnalytics:
    def __init__(self) -> None:
        if not DUCKDB_AVAILABLE:
            raise ImportError(
                "DuckDB is not installed. Install with: pip install duckdb"
            )
        self._conn: duckdb.DuckDBPyConnection = duckdb.connect(database=":memory:")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DuckDBAnalytics":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def register_portfolio_trades(self, trades: pd.DataFrame, table_name: str = "trades") -> None:
        self._conn.register(trades, table_name)

    def register_price_data(
        self, prices: pd.DataFrame, table_name: str = "prices"
    ) -> None:
        self._conn.register(prices, table_name)

    def query(self, sql: str, **kwargs: Any) -> pd.DataFrame | None:
        try:
            result = self._conn.sql(sql, **kwargs).fetchdf()
            return result
        except Exception as e:
            logger.error("DuckDB query failed: %s\nSQL: %s", e, sql)
            return None

    def correlation_matrix(
        self, prices: pd.DataFrame, method: str = "pearson"
    ) -> pd.DataFrame | None:
        if DUCKDB_AVAILABLE:
            try:
                self.register_price_data(prices, "price_data")
                safe_cols = []
                for col in prices.columns:
                    if col == "date":
                        continue
                    _validate_identifier(col, context="column name")
                    safe_cols.append(col)
                col_list = ", ".join(
                    '"%s"' % col for col in safe_cols
                )
                result = self._conn.sql(
                    "SELECT CORR_MATRIX(%s) FROM price_data" % col_list
                ).fetchdf()
                return result
            except Exception as e:
                logger.warning(
                    "DuckDB CORR_MATRIX failed (%s), falling back to pandas for %s correlation",
                    e, method,
                )
        return self._correlation_matrix_pandas(prices, method)

    def _correlation_matrix_pandas(
        self, prices: pd.DataFrame, method: str
    ) -> pd.DataFrame:
        symbol_cols = [c for c in prices.columns if c != "date"]
        returns = prices[symbol_cols].pct_change().dropna()
        return returns.corr(method=method)

    def rolling_correlation(
        self,
        symbol_a: str,
        symbol_b: str,
        prices: pd.DataFrame,
        window: int = 30,
    ) -> pd.Series | None:
        _validate_identifier(symbol_a, context="symbol_a")
        _validate_identifier(symbol_b, context="symbol_b")
        if window < 2:
            raise ValueError("window must be >= 2")
        if DUCKDB_AVAILABLE:
            try:
                self.register_price_data(prices, "price_data")
                result = self._conn.sql(
                    """
                    SELECT date,
                           CORR(
                               "%s_ret",
                               "%s_ret"
                           ) OVER (ORDER BY date ROWS BETWEEN %d PRECEDING AND CURRENT ROW) AS rolling_corr
                    FROM (
                        SELECT date,
                               "%s" - LAG("%s") OVER (ORDER BY date) AS "%s_ret",
                               "%s" - LAG("%s") OVER (ORDER BY date) AS "%s_ret"
                        FROM price_data
                    )
                    """
                    % (symbol_a, symbol_b, window - 1,
                       symbol_a, symbol_a, symbol_a,
                       symbol_b, symbol_b, symbol_b)
                ).fetchdf()
                return result.set_index("date")["rolling_corr"]
            except Exception as e:
                logger.warning(
                    "DuckDB rolling correlation failed (%s), falling back to pandas loop for %s vs %s",
                    e, symbol_a, symbol_b,
                )
        a_returns = prices[symbol_a].pct_change().dropna()
        b_returns = prices[symbol_b].pct_change().dropna()
        min_len = min(len(a_returns), len(b_returns))
        a = a_returns.iloc[-min_len:].values
        b = b_returns.iloc[-min_len:].values
        n = len(a)
        result = []
        for i in range(window - 1, n):
            window_a = a[i - window + 1 : i + 1]
            window_b = b[i - window + 1 : i + 1]
            if len(window_a) == window and np.std(window_a) > 0 and np.std(window_b) > 0:
                corr = np.corrcoef(window_a, window_b)[0, 1]
                result.append(corr if np.isfinite(corr) else np.nan)
            else:
                result.append(np.nan)
        dates = prices["date"].iloc[window:].iloc[-len(result) :].reset_index(drop=True)
        return pd.Series(result, index=dates, name=f"rolling_corr_{symbol_a}_{symbol_b}")

    def portfolio_volatility(
        self, weights: np.ndarray, prices: pd.DataFrame
    ) -> float | None:
        if DUCKDB_AVAILABLE:
            try:
                returns_df = prices.drop(columns=["date"]).pct_change().dropna()
                cov_matrix = returns_df.cov().values
                portfolio_var = weights @ cov_matrix @ weights
                return float(np.sqrt(portfolio_var * 252))
            except Exception as e:
                logger.warning(
                    "DuckDB portfolio_volatility failed (%s), returning None",
                    e,
                )
        return None

    def sql_aggregation(
        self,
        table_name: str,
        group_by: str,
        agg_expressions: dict[str, str],
        where_clause: str | None = None,
    ) -> pd.DataFrame | None:
        if not DUCKDB_AVAILABLE:
            return None
        _validate_identifier(table_name, context="table_name")
        _validate_identifier(group_by, context="group_by")
        for col in agg_expressions:
            _validate_identifier(col, context="aggregation column")
        aggs = ", ".join(
            "%s AS %s_agg" % (func, col)
            for col, func in agg_expressions.items()
        )
        sql = "SELECT %s, %s FROM %s" % (group_by, aggs, table_name)
        if where_clause:
            sql += " WHERE %s" % where_clause
        sql += " GROUP BY %s" % group_by
        return self.query(sql)

    def run_parquet_analytics(
        self, parquet_path: str, sql: str
    ) -> pd.DataFrame | None:
        if not DUCKDB_AVAILABLE:
            return None
        _validate_path(parquet_path)
        try:
            self._conn.sql("SELECT * FROM read_parquet('%s')" % parquet_path).fetchdf()
            return self.query(sql)
        except Exception as e:
            logger.error("Parquet analytics failed: %s", e)
            return None

    def get_table_info(self, table_name: str) -> list[tuple[str, str, str]] | None:
        if not DUCKDB_AVAILABLE:
            return None
        _validate_identifier(table_name, context="table_name")
        try:
            return self._conn.sql("DESCRIBE %s" % table_name).fetchall()
        except Exception as e:
            logger.warning("DuckDB DESCRIBE failed (%s) for table %s", e, table_name)
            return None
