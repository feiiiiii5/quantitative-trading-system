"""
QuantCore 数据库模块
提供 SQLite 存储和线程安全缓存
"""
import json
import logging
import sqlite3
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "quantcore.db"


class ThreadSafeLRU:
    """线程安全的LRU缓存，支持TTL和前缀删除"""

    def __init__(self, maxsize: int = 200, ttl: int = 60):
        self._maxsize = maxsize
        self._ttl = ttl
        self._cache: OrderedDict[str, tuple[Any, float, int]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._cache:
                value, ts, ttl = self._cache[key]
                if time.time() - ts < ttl:
                    self._cache.move_to_end(key)
                    return value
                del self._cache[key]
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        effective_ttl = ttl if ttl is not None else self._ttl
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            elif len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)
            self._cache[key] = (value, time.time(), int(effective_ttl))

    def delete(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def delete_prefix(self, prefix: str) -> int:
        count = 0
        with self._lock:
            keys_to_delete = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_delete:
                del self._cache[k]
                count += 1
        return count

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


_db_query_cache = ThreadSafeLRU(maxsize=500, ttl=90)


class CacheManager:
    """全局缓存管理器"""

    def __init__(self):
        self._caches: dict[str, ThreadSafeLRU] = {}
        self._lock = threading.Lock()

    def get_cache(self, name: str, maxsize: int = 200, ttl: int = 60) -> ThreadSafeLRU:
        with self._lock:
            if name not in self._caches:
                self._caches[name] = ThreadSafeLRU(maxsize=maxsize, ttl=ttl)
            return self._caches[name]

    def flush(self) -> None:
        with self._lock:
            for cache in self._caches.values():
                cache.clear()


_cache_manager: Optional[CacheManager] = None
_cache_manager_lock = threading.Lock()


def get_cache_manager() -> CacheManager:
    global _cache_manager
    if _cache_manager is None:
        with _cache_manager_lock:
            if _cache_manager is None:
                _cache_manager = CacheManager()
    return _cache_manager


class SQLiteStore:
    """SQLite存储，支持缓冲写入和查询缓存"""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or str(DB_PATH)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_buffer: list[tuple[str, tuple, int]] = []
        self._buffer_lock = threading.Lock()
        self._buffer_max_size = 100
        self._buffer_abs_max = 1000
        self._last_flush = time.time()
        self._buffer_max_retries = 5
        self._dropped_writes = 0
        self._pool: list[sqlite3.Connection] = []
        self._pool_lock = threading.Lock()
        self._pool_max_size = 8
        self._init_db()
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def _create_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-128000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=67108864")
        conn.execute("PRAGMA page_size=4096")
        return conn

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = self._acquire_from_pool()
        try:
            self._local.conn.execute("SELECT 1")
        except sqlite3.OperationalError:
            self._local.conn = self._acquire_from_pool()
        return self._local.conn

    def _acquire_from_pool(self) -> sqlite3.Connection:
        with self._pool_lock:
            if self._pool:
                conn = self._pool.pop()
                try:
                    conn.execute("SELECT 1")
                    return conn
                except sqlite3.OperationalError:
                    try:
                        conn.close()
                    except Exception:
                        pass
        return self._create_conn()

    def _release_to_pool(self, conn: sqlite3.Connection) -> None:
        with self._pool_lock:
            if len(self._pool) < self._pool_max_size:
                try:
                    conn.execute("SELECT 1")
                    self._pool.append(conn)
                    return
                except sqlite3.OperationalError:
                    try:
                        conn.close()
                    except Exception:
                        pass
                return
        try:
            conn.close()
        except Exception:
            pass

    def get_pool_status(self) -> dict:
        with self._pool_lock:
            return {
                "pool_size": len(self._pool),
                "pool_max_size": self._pool_max_size,
                "buffer_size": len(self._write_buffer),
                "buffer_max_size": self._buffer_max_size,
                "dropped_writes": self._dropped_writes,
            }

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS kline (
                symbol TEXT NOT NULL,
                market TEXT NOT NULL,
                kline_type TEXT NOT NULL,
                adjust TEXT NOT NULL DEFAULT '',
                date TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL,
                volume REAL, amount REAL,
                turnover_rate REAL DEFAULT 0,
                PRIMARY KEY (symbol, market, kline_type, adjust, date)
            );
            CREATE INDEX IF NOT EXISTS idx_kline_symbol ON kline(symbol, market);
            CREATE INDEX IF NOT EXISTS idx_kline_date ON kline(date);

            CREATE TABLE IF NOT EXISTS stock_info (
                symbol TEXT PRIMARY KEY,
                name TEXT,
                market TEXT,
                industry TEXT,
                list_date TEXT,
                update_time TEXT
            );

            CREATE TABLE IF NOT EXISTS source_stats (
                source_name TEXT NOT NULL,
                request_type TEXT NOT NULL,
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                avg_latency REAL DEFAULT 0,
                last_success_ts REAL DEFAULT 0,
                update_time TEXT,
                PRIMARY KEY (source_name, request_type)
            );

            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS realtime_cache (
                symbol TEXT PRIMARY KEY,
                data TEXT,
                update_time REAL
            );

            CREATE TABLE IF NOT EXISTS factor_cache (
                symbol TEXT NOT NULL,
                factor_name TEXT NOT NULL,
                date TEXT NOT NULL,
                value REAL,
                PRIMARY KEY (symbol, factor_name, date)
            );

            CREATE TABLE IF NOT EXISTS backtest_results (
                id TEXT PRIMARY KEY,
                strategy_name TEXT,
                symbol TEXT,
                start_date TEXT,
                end_date TEXT,
                params TEXT,
                result_json TEXT,
                created_at TEXT,
                sharpe_ratio REAL,
                total_return REAL,
                max_drawdown REAL
            );

            CREATE TABLE IF NOT EXISTS trade_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                signal_score REAL,
                price REAL,
                created_at TEXT,
                market_regime TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_backtest_symbol ON backtest_results(symbol, strategy_name);
            CREATE INDEX IF NOT EXISTS idx_signals_symbol ON trade_signals(symbol, created_at);
            CREATE INDEX IF NOT EXISTS idx_kline_composite
            ON kline(symbol, market, kline_type, adjust, date DESC);
            CREATE INDEX IF NOT EXISTS idx_config_key ON config(key);
        """)
        conn.execute("PRAGMA wal_autocheckpoint=1000")
        conn.commit()

    def _flush_loop(self) -> None:
        while True:
            try:
                time.sleep(2)
                self._flush_buffer()
            except Exception as e:
                logger.debug(f"Flush loop error: {e}")

    def _flush_buffer(self) -> None:
        with self._buffer_lock:
            if not self._write_buffer:
                return
            buffer = self._write_buffer
            self._write_buffer = []
            self._last_flush = time.time()

        if not buffer:
            return

        try:
            failed = []
            conn = self._get_conn()
            with conn:
                for item in buffer:
                    if len(item) == 2:
                        sql, params = item
                        retries = 0
                    else:
                        sql, params, retries = item
                    try:
                        conn.execute(sql, params)
                    except Exception as e:
                        logger.warning(f"Buffered write error: {e} | sql={sql[:80]}")
                        failed.append((sql, params, retries + 1))
                conn.commit()
            if failed:
                with self._buffer_lock:
                    requeued = 0
                    for sql, params, retries in failed:
                        if retries < self._buffer_max_retries:
                            self._write_buffer.append((sql, params, retries))
                            requeued += 1
                        else:
                            logger.error(f"丢弃持久失败的缓冲写入（已重试{retries}次）: {sql[:80]}")
                if requeued:
                    logger.warning(f"Re-queued {requeued} failed buffered writes")
        except Exception:
            logger.exception("Flush buffer transaction-level error")
            with self._buffer_lock:
                for item in buffer:
                    if len(item) == 2:
                        sql, params = item[0], item[1]
                        retries = 0
                    else:
                        sql, params, retries = item[0], item[1], item[2]
                    if retries < self._buffer_max_retries:
                        self._write_buffer.append((sql, params, retries + 1))
                    else:
                        logger.error(f"丢弃持久失败的缓冲写入（事务错误）: {sql[:80]}")

    def buffered_write(self, sql: str, params: tuple) -> None:
        with self._buffer_lock:
            if len(self._write_buffer) >= self._buffer_abs_max:
                dropped = len(self._write_buffer) - self._buffer_max_size
                self._dropped_writes += dropped
                dropped_samples = [(b[0][:60], b[2]) for b in self._write_buffer[:min(3, dropped)]]
                self._write_buffer = self._write_buffer[-self._buffer_max_size:]
                logger.error(f"写缓冲区溢出，丢弃 {dropped} 条最旧记录（累计丢弃: {self._dropped_writes}），示例: {dropped_samples}")
            self._write_buffer.append((sql, params, 0))
            should_flush = (
                len(self._write_buffer) >= self._buffer_max_size
                or (time.time() - self._last_flush) >= 2
            )
        if should_flush:
            self._flush_buffer()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        conn = self._get_conn()
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor

    def executemany(self, sql: str, params_list: list[tuple]) -> sqlite3.Cursor:
        conn = self._get_conn()
        cursor = conn.executemany(sql, params_list)
        conn.commit()
        return cursor

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        conn = self._get_conn()
        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None

    def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def upsert_kline_rows(self, symbol: str, market: str, kline_type: str,
                          adjust: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        sql = """
            INSERT OR REPLACE INTO kline
            (symbol, market, kline_type, adjust, date, open, high, low, close, volume, amount, turnover_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params_list = []
        for r in rows:
            params_list.append((
                symbol, market, kline_type, adjust,
                str(r.get("date", "")),
                float(r.get("open", 0)),
                float(r.get("high", 0)),
                float(r.get("low", 0)),
                float(r.get("close", 0)),
                float(r.get("volume", 0)),
                float(r.get("amount", 0)),
                float(r.get("turnover_rate", 0)),
            ))

        with self._buffer_lock:
            for p in params_list:
                if len(self._write_buffer) >= self._buffer_abs_max:
                    dropped = len(self._write_buffer) - self._buffer_max_size
                    self._dropped_writes += dropped
                    self._write_buffer = self._write_buffer[-self._buffer_max_size:]
                    logger.error(f"写缓冲区溢出（K线写入），丢弃 {dropped} 条最旧记录（累计丢弃: {self._dropped_writes}）")
                self._write_buffer.append((sql, p, 0))
            should_flush = (
                len(self._write_buffer) >= self._buffer_max_size
                or (time.time() - self._last_flush) >= 2
            )
        if should_flush:
            self._flush_buffer()

        _db_query_cache.delete_prefix(f"kline_{symbol}_")
        return len(rows)

    def load_kline_rows(self, symbol: str, market: str, kline_type: str,
                        adjust: str = "", start_date: str = "",
                        end_date: str = "") -> pd.DataFrame:
        cache_key = f"kline_{symbol}_{market}_{kline_type}_{adjust}_{start_date}_{end_date}"
        cached = _db_query_cache.get(cache_key)
        if cached is not None:
            return cached.copy()

        sql = "SELECT * FROM kline WHERE symbol=? AND market=? AND kline_type=?"
        params: list[Any] = [symbol, market, kline_type]

        if adjust:
            sql += " AND adjust=?"
            params.append(adjust)
        if start_date:
            sql += " AND date>=?"
            params.append(start_date)
        if end_date:
            sql += " AND date<=?"
            params.append(end_date)

        sql += " ORDER BY date ASC"

        try:
            rows = self.fetchall(sql, tuple(params))
            if rows:
                df = pd.DataFrame(rows)
                for col in ["open", "high", "low", "close", "volume", "amount"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                _db_query_cache.set(cache_key, df)
                return df
        except Exception as e:
            logger.debug(f"Load kline error: {e}")

        return pd.DataFrame()

    def record_source_request(self, source_name: str, request_type: str,
                              success: bool, latency: float = 0) -> None:
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        if success:
            sql = """
                INSERT INTO source_stats (source_name, request_type, success_count, fail_count, avg_latency, last_success_ts, update_time)
                VALUES (?, ?, 1, 0, ?, ?, ?)
                ON CONFLICT(source_name, request_type) DO UPDATE SET
                    success_count = success_count + 1,
                    avg_latency = (avg_latency * success_count + ?) / (success_count + 1),
                    last_success_ts = ?,
                    update_time = ?
            """
            ts = time.time()
            self.buffered_write(sql, (source_name, request_type, latency, ts, now_str, latency, ts, now_str))
        else:
            sql = """
                INSERT INTO source_stats (source_name, request_type, success_count, fail_count, avg_latency, last_success_ts, update_time)
                VALUES (?, ?, 0, 1, 0, 0, ?)
                ON CONFLICT(source_name, request_type) DO UPDATE SET
                    fail_count = fail_count + 1,
                    update_time = ?
            """
            self.buffered_write(sql, (source_name, request_type, now_str, now_str))

    def get_source_stats(self, source_name: str = "", request_type: str = "") -> list[dict]:
        sql = "SELECT * FROM source_stats"
        params: list[Any] = []
        conditions = []
        if source_name:
            conditions.append("source_name=?")
            params.append(source_name)
        if request_type:
            conditions.append("request_type=?")
            params.append(request_type)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        return self.fetchall(sql, tuple(params))

    def get_config(self, key: str, default: Any = None) -> Any:
        row = self.fetchone("SELECT value FROM config WHERE key=?", (key,))
        if row:
            try:
                return json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                return row["value"]
        return default

    def set_config(self, key: str, value: Any) -> None:
        value_str = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        self.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value_str))

    def get_realtime_cache(self, symbol: str) -> Optional[dict]:
        row = self.fetchone("SELECT data, update_time FROM realtime_cache WHERE symbol=?", (symbol,))
        if row:
            try:
                return json.loads(row["data"])
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    def set_realtime_cache(self, symbol: str, data: dict) -> None:
        data_str = json.dumps(data, ensure_ascii=False)
        now = time.time()
        self.buffered_write(
            "INSERT OR REPLACE INTO realtime_cache (symbol, data, update_time) VALUES (?, ?, ?)",
            (symbol, data_str, now)
        )

    def save_backtest_result(self, strategy_name, symbol, start_date, end_date, params, result) -> str:
        result_id = uuid.uuid4().hex
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(result, "__dict__"):
            result_data = dict(result.__dict__)
        elif isinstance(result, dict):
            result_data = result
        else:
            result_data = {"value": str(result)}
        result_json = json.dumps(result_data, ensure_ascii=False, default=str)
        params_json = json.dumps(params or {}, ensure_ascii=False, default=str)
        self.execute(
            """
            INSERT INTO backtest_results
            (id, strategy_name, symbol, start_date, end_date, params, result_json, created_at,
             sharpe_ratio, total_return, max_drawdown)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result_id, strategy_name, symbol, start_date, end_date, params_json, result_json, created_at,
                float(result_data.get("sharpe_ratio", 0) or 0),
                float(result_data.get("total_return", 0) or 0),
                float(result_data.get("max_drawdown", 0) or 0),
            ),
        )
        return result_id

    def get_backtest_by_id(self, result_id: str) -> Optional[dict]:
        row = self.fetchone(
            "SELECT * FROM backtest_results WHERE id=?",
            (result_id,),
        )
        return dict(row) if row else None

    def get_backtest_history(self, symbol=None, strategy_name=None, limit=20) -> list[dict]:
        sql = "SELECT * FROM backtest_results"
        params: list[Any] = []
        conditions = []
        if symbol:
            conditions.append("symbol=?")
            params.append(symbol)
        if strategy_name:
            conditions.append("strategy_name=?")
            params.append(strategy_name)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(limit))
        rows = self.fetchall(sql, tuple(params))
        for row in rows:
            try:
                row["params"] = json.loads(row.get("params") or "{}")
                row["result"] = json.loads(row.get("result_json") or "{}")
            except (json.JSONDecodeError, TypeError):
                row["result"] = {}
            row.pop("result_json", None)
        return rows

    def save_trade_signal(self, symbol, strategy_name, signal_type, score, price, regime="") -> None:
        self.buffered_write(
            """
            INSERT INTO trade_signals
            (symbol, strategy_name, signal_type, signal_score, price, created_at, market_regime)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                strategy_name,
                signal_type,
                float(score or 0),
                float(price or 0),
                time.strftime("%Y-%m-%d %H:%M:%S"),
                regime or "",
            ),
        )

    def get_factor_cache(self, symbol, factor_name, start_date="", end_date="") -> pd.DataFrame:
        sql = "SELECT date, value FROM factor_cache WHERE symbol=? AND factor_name=?"
        params: list[Any] = [symbol, factor_name]
        if start_date:
            sql += " AND date>=?"
            params.append(start_date)
        if end_date:
            sql += " AND date<=?"
            params.append(end_date)
        sql += " ORDER BY date ASC"
        rows = self.fetchall(sql, tuple(params))
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["date", "value"])

    def set_factor_cache(self, symbol, factor_name, dates, values) -> None:
        params = []
        for d, v in zip(dates, values):
            try:
                value = float(v) if v is not None and pd.notna(v) else None
            except (TypeError, ValueError):
                value = None
            params.append((symbol, factor_name, str(d)[:10], value))
        if params:
            self.executemany(
                "INSERT OR REPLACE INTO factor_cache (symbol, factor_name, date, value) VALUES (?, ?, ?, ?)",
                params,
            )

    def get_performance_stats(self) -> dict:
        total = self.fetchone("SELECT COUNT(*) AS n FROM backtest_results") or {"n": 0}
        avg = self.fetchone("SELECT AVG(sharpe_ratio) AS avg_sharpe FROM backtest_results") or {"avg_sharpe": 0}
        best = self.fetchone(
            "SELECT strategy_name, symbol, sharpe_ratio, total_return FROM backtest_results ORDER BY sharpe_ratio DESC LIMIT 1"
        ) or {}
        signals = self.fetchone("SELECT COUNT(*) AS n FROM trade_signals") or {"n": 0}
        return {
            "total_backtests": int(total.get("n", 0) or 0),
            "avg_sharpe": round(float(avg.get("avg_sharpe", 0) or 0), 4),
            "best_strategy": best,
            "total_signals": int(signals.get("n", 0) or 0),
        }

    def cleanup_stale_data(self, days: int = 30) -> dict:
        cutoff = time.time() - days * 86400
        try:
            conn = self._get_conn()
            with conn:
                r1 = conn.execute("DELETE FROM realtime_cache WHERE update_time < ?", (cutoff,))
                conn.commit()
                return {"deleted_cache": r1.rowcount}
        except Exception as e:
            logger.debug(f"Cleanup error: {e}")
            return {"error": str(e)}

    def compress_old_data(self, days: int = 90) -> dict:
        """将90天以前的数据按周聚合压缩存储"""
        try:
            cutoff = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
            conn = self._get_conn()

            rows = self.fetchall(
                "SELECT symbol, market, kline_type, adjust, COUNT(*) as cnt FROM kline WHERE date < ? GROUP BY symbol, market, kline_type, adjust",
                (cutoff,),
            )

            compressed_count = 0
            deleted_count = 0

            for row in rows:
                symbol = row["symbol"]
                market = row["market"]
                kline_type = row["kline_type"]
                adjust = row["adjust"]
                cnt = row.get("cnt", 0)
                if cnt < 14:
                    continue

                detail_rows = self.fetchall(
                    "SELECT date, open, high, low, close, volume, amount, turnover_rate FROM kline WHERE symbol=? AND market=? AND kline_type=? AND adjust=? AND date < ? ORDER BY date ASC",
                    (symbol, market, kline_type, adjust, cutoff),
                )
                if not detail_rows or len(detail_rows) < 5:
                    continue

                df = pd.DataFrame(detail_rows)
                for col in ["open", "high", "low", "close", "volume", "amount", "turnover_rate"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")

                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")

                weekly = df.resample("W").agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                    "amount": "sum",
                    "turnover_rate": "mean",
                }).dropna(subset=["close"])

                if weekly.empty:
                    continue

                conn.execute(
                    "DELETE FROM kline WHERE symbol=? AND market=? AND kline_type=? AND adjust=? AND date < ?",
                    (symbol, market, kline_type, adjust, cutoff),
                )
                deleted_count += cnt

                for idx, wr in weekly.iterrows():
                    conn.execute(
                        """INSERT OR REPLACE INTO kline
                        (symbol, market, kline_type, adjust, date, open, high, low, close, volume, amount, turnover_rate)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            symbol, market, kline_type, adjust,
                            idx.strftime("%Y-%m-%d"),
                            round(float(wr.get("open", 0)), 4),
                            round(float(wr.get("high", 0)), 4),
                            round(float(wr.get("low", 0)), 4),
                            round(float(wr.get("close", 0)), 4),
                            int(wr.get("volume", 0)),
                            round(float(wr.get("amount", 0)), 2),
                            round(float(wr.get("turnover_rate", 0)), 4),
                        ),
                    )
                    compressed_count += 1

            conn.commit()
            _db_query_cache.clear()
            return {"deleted_daily": deleted_count, "compressed_weekly": compressed_count}
        except Exception as e:
            logger.debug(f"Compress error: {e}")
            return {"error": str(e)}

    def close(self) -> None:
        self._flush_buffer()
        if hasattr(self._local, "conn") and self._local.conn is not None:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None
        with self._pool_lock:
            for conn in self._pool:
                try:
                    conn.close()
                except Exception:
                    pass
            self._pool.clear()


_db_instance: Optional[SQLiteStore] = None
_db_lock = threading.Lock()


def get_db() -> SQLiteStore:
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                _db_instance = SQLiteStore()
    return _db_instance
