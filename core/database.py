"""
QuantCore 数据库模块
提供 SQLite 存储和线程安全缓存
"""
import json
import logging
import sqlite3
import threading
import time
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
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._cache:
                value, ts = self._cache[key]
                if time.time() - ts < self._ttl:
                    return value
                del self._cache[key]
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        effective_ttl = ttl if ttl is not None else self._ttl
        with self._lock:
            if len(self._cache) >= self._maxsize and key not in self._cache:
                oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
            self._cache[key] = (value, time.time())
            self._last_ttl = effective_ttl

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


_db_query_cache = ThreadSafeLRU(maxsize=200, ttl=60)


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
        self._write_buffer: list[tuple[str, tuple]] = []
        self._buffer_lock = threading.Lock()
        self._buffer_max_size = 50
        self._last_flush = time.time()
        self._init_db()
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path, timeout=10)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.execute("PRAGMA cache_size=-64000")
            self._local.conn.execute("PRAGMA temp_store=MEMORY")
        return self._local.conn

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
        """)
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
            buffer = self._write_buffer[:]
            self._write_buffer.clear()
            self._last_flush = time.time()

        if not buffer:
            return

        try:
            conn = self._get_conn()
            with conn:
                for sql, params in buffer:
                    try:
                        conn.execute(sql, params)
                    except Exception as e:
                        logger.debug(f"Buffered write error: {e}")
                conn.commit()
        except Exception as e:
            logger.debug(f"Flush buffer error: {e}")

    def buffered_write(self, sql: str, params: tuple) -> None:
        with self._buffer_lock:
            self._write_buffer.append((sql, params))
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
                self._write_buffer.append((sql, p))
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

    def close(self) -> None:
        self._flush_buffer()
        if hasattr(self._local, "conn") and self._local.conn is not None:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None


_db_instance: Optional[SQLiteStore] = None
_db_lock = threading.Lock()


def get_db() -> SQLiteStore:
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                _db_instance = SQLiteStore()
    return _db_instance
