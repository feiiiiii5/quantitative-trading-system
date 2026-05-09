__all__ = [
    "PointInTimeDB",
    "PITQuery",
    "create_pit_db",
]

import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_PIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS pit_data (
    symbol       TEXT NOT NULL,
    report_period TEXT NOT NULL,
    publish_date  TEXT NOT NULL,
    metric        TEXT NOT NULL,
    value         REAL,
    updated_at    TEXT DEFAULT (datetime('now')),
    source        TEXT DEFAULT '',
    PRIMARY KEY (symbol, report_period, publish_date, metric)
);

CREATE INDEX IF NOT EXISTS idx_pit_symbol_metric_date
    ON pit_data (symbol, metric, publish_date);

CREATE INDEX IF NOT EXISTS idx_pit_symbol_date
    ON pit_data (symbol, publish_date);

CREATE TABLE IF NOT EXISTS pit_price_adjust (
    symbol        TEXT NOT NULL,
    date          TEXT NOT NULL,
    adj_factor    REAL DEFAULT 1.0,
    is_suspended  INTEGER DEFAULT 0,
    PRIMARY KEY (symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_adj_symbol_date
    ON pit_price_adjust (symbol, date);

CREATE TABLE IF NOT EXISTS pit_snapshot (
    symbol       TEXT NOT NULL,
    as_of_date   TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    PRIMARY KEY (symbol, as_of_date)
);
"""


@dataclass
class PITQuery:
    symbol: str
    metric: str
    as_of_date: str
    report_period: str | None = None
    lookback_periods: int = 4


class PointInTimeDB:
    def __init__(self, db_path: str | Path = ":memory:"):
        self._path = Path(db_path) if db_path != ":memory:" else ":memory:"
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_PIT_SCHEMA)

    def insert_financial(
        self,
        symbol: str,
        report_period: str,
        publish_date: str,
        metric: str,
        value: float,
        source: str = "",
    ) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO pit_data
            (symbol, report_period, publish_date, metric, value, source)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (symbol, report_period, publish_date, metric, value, source),
        )

    def insert_financial_batch(
        self,
        records: list[tuple[str, str, str, str, float, str]],
    ) -> int:
        if not records:
            return 0
        self._conn.executemany(
            """INSERT OR REPLACE INTO pit_data
            (symbol, report_period, publish_date, metric, value, source)
            VALUES (?, ?, ?, ?, ?, ?)""",
            records,
        )
        return len(records)

    def insert_from_dataframe(
        self,
        df: pd.DataFrame,
        symbol_col: str = "symbol",
        report_period_col: str = "report_period",
        publish_date_col: str = "publish_date",
        metric_col: str = "metric",
        value_col: str = "value",
        source: str = "",
    ) -> int:
        if df.empty:
            return 0
        records = []
        for _, row in df.iterrows():
            records.append((
                str(row[symbol_col]),
                str(row[report_period_col]),
                str(row[publish_date_col]),
                str(row[metric_col]),
                float(row[value_col]),
                source,
            ))
        return self.insert_financial_batch(records)

    def query(self, q: PITQuery) -> list[dict[str, Any]]:
        if q.report_period:
            sql = (
                "SELECT * FROM pit_data "
                "WHERE symbol=? AND metric=? AND publish_date<=? AND report_period=? "
                "ORDER BY publish_date DESC, report_period DESC "
                "LIMIT ?"
            )
            rows = self._conn.execute(
                sql, (q.symbol, q.metric, q.as_of_date, q.report_period, q.lookback_periods)
            ).fetchall()
        else:
            sql = (
                "SELECT * FROM pit_data "
                "WHERE symbol=? AND metric=? AND publish_date<=? "
                "ORDER BY publish_date DESC, report_period DESC "
                "LIMIT ?"
            )
            rows = self._conn.execute(
                sql, (q.symbol, q.metric, q.as_of_date, q.lookback_periods)
            ).fetchall()

        return [dict(r) for r in rows]

    def query_latest(self, q: PITQuery) -> dict[str, Any] | None:
        results = self.query(PITQuery(
            symbol=q.symbol,
            metric=q.metric,
            as_of_date=q.as_of_date,
            lookback_periods=1,
        ))
        return results[0] if results else None

    def query_multiple_metrics(
        self,
        symbol: str,
        metrics: list[str],
        as_of_date: str,
    ) -> dict[str, dict[str, Any] | None]:
        result = {}
        for metric in metrics:
            q = PITQuery(symbol=symbol, metric=metric, as_of_date=as_of_date)
            result[metric] = self.query_latest(q)
        return result

    def query_time_series(
        self,
        symbol: str,
        metric: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        sql = (
            "SELECT publish_date, report_period, value FROM pit_data "
            "WHERE symbol=? AND metric=? AND publish_date>=? AND publish_date<=? "
            "ORDER BY publish_date ASC"
        )
        rows = self._conn.execute(sql, (symbol, metric, start_date, end_date)).fetchall()
        if not rows:
            return pd.DataFrame(columns=["publish_date", "report_period", "value"])
        return pd.DataFrame([dict(r) for r in rows])

    def query_cross_section(
        self,
        metric: str,
        as_of_date: str,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        if symbols:
            placeholders = ",".join("?" * len(symbols))
            sql = (
                f"SELECT p.* FROM pit_data p "
                f"INNER JOIN ("
                f"  SELECT symbol, MAX(publish_date) as max_pd "
                f"  FROM pit_data "
                f"  WHERE metric=? AND publish_date<=? AND symbol IN ({placeholders}) "
                f"  GROUP BY symbol"
                f") latest ON p.symbol=latest.symbol AND p.publish_date=latest.max_pd "
                f"WHERE p.metric=? "
                f"ORDER BY p.symbol"
            )
            rows = self._conn.execute(sql, [metric, as_of_date] + symbols + [metric]).fetchall()
        else:
            sql = (
                "SELECT p.* FROM pit_data p "
                "INNER JOIN ("
                "  SELECT symbol, MAX(publish_date) as max_pd "
                "  FROM pit_data "
                "  WHERE metric=? AND publish_date<=? "
                "  GROUP BY symbol"
                ") latest ON p.symbol=latest.symbol AND p.publish_date=latest.max_pd "
                "WHERE p.metric=? "
                "ORDER BY p.symbol"
            )
            rows = self._conn.execute(sql, (metric, as_of_date, metric)).fetchall()

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])

    def insert_price_adjust(
        self,
        symbol: str,
        date: str,
        adj_factor: float = 1.0,
        is_suspended: bool = False,
    ) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO pit_price_adjust
            (symbol, date, adj_factor, is_suspended)
            VALUES (?, ?, ?, ?)""",
            (symbol, date, adj_factor, int(is_suspended)),
        )

    def query_adjusted_price(
        self,
        symbol: str,
        date: str,
        close_price: float,
    ) -> float:
        row = self._conn.execute(
            "SELECT adj_factor FROM pit_price_adjust WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 1",
            (symbol, date),
        ).fetchone()
        if row:
            return close_price * row["adj_factor"]
        return close_price

    def is_suspended(self, symbol: str, date: str) -> bool:
        row = self._conn.execute(
            "SELECT is_suspended FROM pit_price_adjust WHERE symbol=? AND date=?",
            (symbol, date),
        ).fetchone()
        return bool(row and row["is_suspended"])

    def save_snapshot(
        self,
        symbol: str,
        as_of_date: str,
        metrics: dict[str, float],
    ) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO pit_snapshot
            (symbol, as_of_date, metrics_json)
            VALUES (?, ?, ?)""",
            (symbol, as_of_date, json.dumps(metrics)),
        )

    def load_snapshot(
        self,
        symbol: str,
        as_of_date: str,
    ) -> dict[str, float] | None:
        row = self._conn.execute(
            "SELECT metrics_json FROM pit_snapshot WHERE symbol=? AND as_of_date=?",
            (symbol, as_of_date),
        ).fetchone()
        if row:
            return json.loads(row["metrics_json"])
        return None

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.commit()
        self.close()

    def stats(self) -> dict[str, int]:
        pit_count = self._conn.execute("SELECT COUNT(*) FROM pit_data").fetchone()[0]
        adj_count = self._conn.execute("SELECT COUNT(*) FROM pit_price_adjust").fetchone()[0]
        snap_count = self._conn.execute("SELECT COUNT(*) FROM pit_snapshot").fetchone()[0]
        return {
            "pit_records": pit_count,
            "adjust_records": adj_count,
            "snapshots": snap_count,
        }


def create_pit_db(db_path: str | Path = ":memory:") -> PointInTimeDB:
    return PointInTimeDB(db_path)
