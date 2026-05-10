from __future__ import annotations

"""
QuantCore 数据库模块
提供 SQLite 存储和线程安全缓存
"""
import asyncio
import contextlib
import hashlib
import heapq
import json
import logging
import sqlite3
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, cast

import pandas as pd

logger = logging.getLogger(__name__)

__all__ = [
    'ThreadSafeLRU',
    'CacheManager',
    'SQLiteStore',
    'AsyncDatabaseSession',
    'AsyncWriteQueue',
    'get_db',
    'get_cache_manager',
]

def _safe_log(log_func: Any, *args: Any, **kwargs: Any) -> None:
    with contextlib.suppress(ValueError, OSError, AttributeError):
        log_func(*args, **kwargs)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "quantcore.db"


class ThreadSafeLRU:
    """线程安全的LRU缓存，支持TTL、LFU淘汰和前缀删除"""

    def __init__(self, maxsize: int = 200, ttl: int = 60):
        self._maxsize = maxsize
        self._ttl = ttl
        self._cache: OrderedDict[str, tuple[Any, float, int]] = OrderedDict()
        self._freq: dict[str, int] = {}
        self._heap: list[tuple[int, float, str]] = []
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key in self._cache:
                value, ts, ttl = self._cache[key]
                if time.monotonic() - ts < float(ttl):
                    self._cache.move_to_end(key)
                    self._freq[key] = self._freq.get(key, 0) + 1
                    self._hits += 1
                    return value
                del self._cache[key]
                self._freq.pop(key, None)
            self._misses += 1
        return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        effective_ttl = ttl if ttl is not None else self._ttl
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            elif len(self._cache) >= self._maxsize:
                self._evict_lfu()
            self._cache[key] = (value, time.monotonic(), int(effective_ttl))
            self._freq[key] = 1
            heapq.heappush(self._heap, (1, time.monotonic(), key))

    def _evict_lfu(self) -> None:
        while self._heap:
            freq, _, key = heapq.heappop(self._heap)
            if key in self._cache:
                current_freq = self._freq.get(key, 0)
                if current_freq <= freq:
                    self._cache.pop(key, None)
                    self._freq.pop(key, None)
                    return
                heapq.heappush(self._heap, (current_freq, time.monotonic(), key))
        if self._cache:
            key_to_evict = next(iter(self._cache))
            self._cache.pop(key_to_evict, None)
            self._freq.pop(key_to_evict, None)

    def delete(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)
            self._freq.pop(key, None)

    def delete_prefix(self, prefix: str) -> int:
        count = 0
        with self._lock:
            keys_to_delete = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_delete:
                del self._cache[k]
                self._freq.pop(k, None)
                count += 1
        return count

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._freq.clear()
            self._heap.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "maxsize": self._maxsize,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total else 0,
            "heap_size": len(self._heap),
        }


_db_query_cache = ThreadSafeLRU(maxsize=10000, ttl=300)


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


_cache_manager: CacheManager | None = None
_cache_manager_lock = threading.Lock()


def get_cache_manager() -> CacheManager:
    global _cache_manager
    if _cache_manager is None:
        with _cache_manager_lock:
            if _cache_manager is None:
                _cache_manager = CacheManager()
    return _cache_manager


class _Transaction:
    def __init__(self, store: 'SQLiteStore'):
        self._store = store
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> '_Transaction':
        conn = self._store._get_conn()
        conn.execute("BEGIN")
        self._conn = conn
        return self

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        assert self._conn is not None
        return self._conn.execute(sql, params)

    def executemany(self, sql: str, params_list: list[tuple]) -> sqlite3.Cursor:
        assert self._conn is not None
        return self._conn.executemany(sql, params_list)

    def commit(self) -> None:
        if self._conn:
            self._conn.commit()

    def rollback(self) -> None:
        if self._conn:
            self._conn.rollback()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()


class SQLiteStore:
    """SQLite存储，支持缓冲写入和查询缓存"""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or str(DB_PATH)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_buffer: list[tuple[str, tuple, int, float]] = []
        self._buffer_lock = threading.Lock()
        self._buffer_max_size = 100
        self._buffer_abs_max = 1000
        self._last_flush = time.monotonic()
        self._buffer_max_retries = 5
        self._dropped_writes = 0
        self._pool: list[sqlite3.Connection] = []
        self._pool_lock = threading.Lock()
        self._pool_max_size = 16
        self._read_pool: list[sqlite3.Connection] = []
        self._read_pool_lock = threading.Lock()
        self._read_pool_max_size = 4
        self._stop_flush = threading.Event()
        self._init_db()
        self._setup_read_pool()
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()
        try:
            import atexit
            atexit.register(self._flush_buffer)
        except (ImportError, AttributeError):
            pass

    def _create_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-256000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=134217728")
        conn.execute("PRAGMA busy_timeout=8000")
        conn.execute("PRAGMA journal_size_limit=134217728")
        return conn

    def _get_conn(self) -> sqlite3.Connection:
        raw_conn: sqlite3.Connection | None = cast(
            sqlite3.Connection | None,
            getattr(self._local, "conn", None),
        )
        if raw_conn is None:
            result_conn: sqlite3.Connection = self._acquire_from_pool()
            self._local.conn = result_conn
            return result_conn
        try:
            raw_conn.execute("SELECT 1")
            return raw_conn
        except sqlite3.OperationalError:
            retry_conn: sqlite3.Connection = self._acquire_from_pool()
            self._local.conn = retry_conn
            return retry_conn

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
                    except Exception as e:
                        logger.debug("Error closing stale pool connection: %s", e)
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
                    except Exception as e:
                        logger.debug("Error closing rejected pool connection: %s", e)
                return
        try:
            conn.close()
        except Exception as e:
            logger.debug("Error closing overflow connection: %s", e)

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
        try:
            conn.execute("PRAGMA wal_autocheckpoint=100")
            conn.execute("PRAGMA optimize")
            conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
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
                CREATE INDEX IF NOT EXISTS idx_backtest_recent ON backtest_results(created_at DESC, symbol);
                CREATE INDEX IF NOT EXISTS idx_signals_symbol ON trade_signals(symbol, created_at);
                CREATE INDEX IF NOT EXISTS idx_kline_composite
                ON kline(symbol, market, kline_type, adjust, date DESC);
                CREATE INDEX IF NOT EXISTS idx_source_stats_key ON source_stats(source_name, request_type);
                CREATE INDEX IF NOT EXISTS idx_config_key ON config(key);

                CREATE TABLE IF NOT EXISTS price_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    name TEXT,
                    target_price REAL NOT NULL,
                    direction TEXT NOT NULL DEFAULT 'above',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    triggered INTEGER NOT NULL DEFAULT 0,
                    trigger_price REAL,
                    trigger_time TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                );
                CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON price_alerts(symbol);
                CREATE INDEX IF NOT EXISTS idx_alerts_active ON price_alerts(enabled, triggered);

                CREATE TABLE IF NOT EXISTS financial_pit (
                    symbol TEXT NOT NULL,
                    report_period TEXT NOT NULL,
                    publish_date TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    value REAL,
                    PRIMARY KEY (symbol, report_period, metric, publish_date)
                );
                CREATE INDEX IF NOT EXISTS idx_fin_pit_symbol_date ON financial_pit(symbol, publish_date);

                CREATE TABLE IF NOT EXISTS index_constituent (
                    index_code TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    in_date TEXT NOT NULL,
                    out_date TEXT,
                    PRIMARY KEY (index_code, symbol, in_date)
                );
                CREATE INDEX IF NOT EXISTS idx_idx_const_code_date ON index_constituent(index_code, in_date, out_date);

                CREATE TABLE IF NOT EXISTS data_lineage (
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    source TEXT NOT NULL,
                    version TEXT NOT NULL,
                    ingest_time TEXT NOT NULL,
                    PRIMARY KEY (symbol, date, source)
                );
                CREATE INDEX IF NOT EXISTS idx_lineage_symbol_date ON data_lineage(symbol, date);

                CREATE TABLE IF NOT EXISTS price_anomaly (
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    anomaly_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    details_json TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    PRIMARY KEY (symbol, date, anomaly_type)
                );
                CREATE INDEX IF NOT EXISTS idx_anomaly_symbol_date ON price_anomaly(symbol, date);

                CREATE TABLE IF NOT EXISTS rebalance_schedules (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    symbols TEXT NOT NULL,
                    frequency TEXT NOT NULL DEFAULT 'weekly',
                    drift_threshold REAL NOT NULL DEFAULT 0.05,
                    turnover_cap REAL NOT NULL DEFAULT 0.30,
                    capital REAL NOT NULL DEFAULT 100000,
                    period TEXT NOT NULL DEFAULT '1y',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_check_at TEXT,
                    last_result_json TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                );
                CREATE INDEX IF NOT EXISTS idx_rebal_sched_enabled ON rebalance_schedules(enabled);
            """)
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e) and "duplicate" not in str(e):
                logger.error("Database initialization error: %s", e)
                raise
        conn.commit()
        try:
            conn.execute("ALTER TABLE kline ADD COLUMN adj_factor REAL DEFAULT 1.0")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    def _setup_read_pool(self) -> None:
        for _ in range(self._read_pool_max_size):
            conn = self._create_read_conn()
            self._read_pool.append(conn)

    def _create_read_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-256000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=134217728")
        conn.execute("PRAGMA query_only=ON")
        return conn

    def _acquire_read_conn(self) -> sqlite3.Connection:
        with self._read_pool_lock:
            while self._read_pool:
                conn = self._read_pool.pop()
                try:
                    conn.execute("SELECT 1")
                    return conn
                except sqlite3.DatabaseError:
                    try:
                        conn.close()
                    except Exception:
                        pass
        return self._create_read_conn()

    def _release_read_conn(self, conn: sqlite3.Connection) -> None:
        with self._read_pool_lock:
            if len(self._read_pool) < self._read_pool_max_size:
                try:
                    conn.execute("SELECT 1")
                    self._read_pool.append(conn)
                    return
                except sqlite3.DatabaseError:
                    try:
                        conn.close()
                    except Exception:
                        pass
                return
        try:
            conn.close()
        except Exception:
            pass

    async def query_async(self, sql: str, params: tuple = ()) -> list[dict]:
        def _query():
            conn = self._acquire_read_conn()
            try:
                cursor = conn.execute(sql, params)
                return [dict(row) for row in cursor.fetchall()]
            finally:
                self._release_read_conn(conn)
        return await asyncio.to_thread(_query)

    async def query_one_async(self, sql: str, params: tuple = ()) -> dict | None:
        def _query():
            conn = self._acquire_read_conn()
            try:
                cursor = conn.execute(sql, params)
                row = cursor.fetchone()
                return dict(row) if row else None
            finally:
                self._release_read_conn(conn)
        return await asyncio.to_thread(_query)

    def _flush_loop(self) -> None:
        while not self._stop_flush.is_set():
            try:
                if self._stop_flush.wait(timeout=2):
                    break
                self._flush_buffer()
            except Exception as e:
                logger.debug("Flush loop error: %s", e)

    def _flush_buffer(self) -> None:
        with self._buffer_lock:
            if not self._write_buffer:
                return
            now = time.monotonic()
            ready = []
            deferred = []
            for item in self._write_buffer:
                if len(item) == 4:
                    sql, params, retries, next_retry = item
                    if now >= next_retry:
                        ready.append((sql, params, retries))
                    else:
                        deferred.append(item)
                else:
                    sql, params = item[0], item[1]
                    retries = 0
                    ready.append((sql, params, retries))
            buffer = ready
            self._write_buffer = deferred
            self._last_flush = now

        if not buffer:
            return

        try:
            failed = []
            conn = self._get_conn()
            with conn:
                for sql, params, retries in buffer:
                    try:
                        conn.execute(sql, params)
                    except Exception as e:
                        _safe_log(logger.warning, f"Buffered write error: {e} | sql={sql[:80]}")
                        failed.append((sql, params, retries + 1))
                conn.commit()
            if failed:
                with self._buffer_lock:
                    requeued = 0
                    for sql, params, retries in failed:
                        if retries < self._buffer_max_retries:
                            backoff = min(2 ** retries, 30)
                            next_retry = time.monotonic() + backoff
                            self._write_buffer.append((sql, params, retries, next_retry))
                            requeued += 1
                        else:
                            _safe_log(logger.error, f"丢弃持久失败的缓冲写入（已重试{retries}次）: {sql[:80]}")
                if requeued:
                    _safe_log(logger.warning, f"Re-queued {requeued} failed buffered writes with exponential backoff")
        except Exception as e:
            _safe_log(logger.exception, f"Flush buffer transaction-level error: {e}")
            with self._buffer_lock:
                for sql, params, retries in buffer:
                    if retries < self._buffer_max_retries:
                        backoff = min(2 ** (retries + 1), 30)
                        next_retry = time.monotonic() + backoff
                        self._write_buffer.append((sql, params, retries + 1, next_retry))
                    else:
                        _safe_log(logger.error, f"丢弃持久失败的缓冲写入（事务错误）: {sql[:80]}")

    def buffered_write(self, sql: str, params: tuple) -> None:
        with self._buffer_lock:
            if len(self._write_buffer) >= self._buffer_abs_max:
                dropped = len(self._write_buffer) - self._buffer_max_size
                self._dropped_writes += dropped
                dropped_samples = [(b[0][:60], b[2] if len(b) > 2 else 0) for b in self._write_buffer[:min(3, dropped)]]
                self._write_buffer = self._write_buffer[-self._buffer_max_size:]
                logger.error("写缓冲区溢出，丢弃 %s 条最旧记录（累计丢弃: %s），示例: %s", dropped, self, dropped_samples)
            self._write_buffer.append((sql, params, 0, 0.0))

    def _batch_execute(self, items: list[tuple[str, tuple]]) -> None:
        if not items:
            return
        try:
            conn = self._get_conn()
            with conn:
                for sql, params in items:
                    try:
                        conn.execute(sql, params)
                    except Exception as e:
                        logger.warning("Batch execute item error: %s | sql=%s", e, sql[:80])
                conn.commit()
        except Exception as e:
            logger.error("Batch execute transaction error: %s", e)
            for sql, params in items:
                self.buffered_write(sql, params)

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

    def transaction(self):
        return _Transaction(self)

    def fetchone(self, sql: str, params: tuple = ()) -> dict | None:
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

    def fetchall_cached(self, sql: str, params: tuple = (), ttl: float = 60.0) -> list[dict]:
        cache_key = hashlib.md5(f"{sql}:{params}".encode()).hexdigest()[:16]
        cached = _db_query_cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for query key=%s", cache_key)
            return cached
        rows = self.fetchall(sql, params)
        _db_query_cache.set(cache_key, rows, ttl=int(ttl))
        logger.debug("Cache miss for query key=%s, stored result", cache_key)
        return rows

    def invalidate_cache(self, pattern: str = "") -> int:
        if not pattern:
            count = len(_db_query_cache)
            _db_query_cache.clear()
            logger.debug("Invalidated entire query cache (%d entries)", count)
            return count
        return _db_query_cache.delete_prefix(pattern)

    def fetch(self, sql: str, params: tuple = ()) -> list[dict]:
        return self.fetchall(sql, params)

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
                    logger.error("写缓冲区溢出（K线写入），丢弃 %s 条最旧记录（累计丢弃: %s）", dropped, self)
                self._write_buffer.append((sql, p, 0, 0.0))

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

        sql += " ORDER BY date ASC LIMIT 50000"

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
            logger.debug("Load kline error: %s", e)

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
        sql += " LIMIT 1000"
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

    def get_realtime_cache(self, symbol: str) -> dict | None:
        row = self.fetchone("SELECT data, update_time FROM realtime_cache WHERE symbol=?", (symbol,))
        if row:
            try:
                data_str: str = row["data"]
                return cast(dict, json.loads(data_str))
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

    def get_backtest_by_id(self, result_id: str) -> dict | None:
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
        sql += " ORDER BY date ASC LIMIT 1000"
        rows = self.fetchall(sql, tuple(params))
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["date", "value"])

    def set_factor_cache(self, symbol, factor_name, dates, values) -> None:
        params = []
        for d, v in zip(dates, values, strict=False):
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
            logger.debug("Cleanup error: %s", e)
            return {"error": str(e)}

    def compress_old_data(self, days: int = 90) -> dict:
        try:
            cutoff = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
            conn = self._get_conn()

            all_rows = self.fetchall(
                "SELECT symbol, market, kline_type, adjust, date, open, high, low, close, volume, amount, turnover_rate FROM kline WHERE date < ? ORDER BY symbol, market, kline_type, adjust, date ASC LIMIT 50000",
                (cutoff,),
            )

            if not all_rows:
                return {"deleted_daily": 0, "compressed_weekly": 0}

            df = pd.DataFrame(all_rows)
            for col in ["open", "high", "low", "close", "volume", "amount", "turnover_rate"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            df["date"] = pd.to_datetime(df["date"])

            compressed_count = 0
            deleted_count = 0

            for (symbol, market, kline_type, adjust), group in df.groupby(["symbol", "market", "kline_type", "adjust"]):
                if len(group) < 14:
                    continue

                group = group.set_index("date")
                weekly = group.resample("W").agg({
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
                deleted_count += len(group)

                for idx, wr in weekly.to_dict("index").items():
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
            logger.debug("Compress error: %s", e)
            return {"error": str(e)}

    def close(self) -> None:
        """关闭所有数据库连接，释放资源"""
        self._stop_flush.set()
        if self._flush_thread.is_alive():
            self._flush_thread.join(timeout=5)
        self._flush_buffer()
        if hasattr(self._local, "conn") and self._local.conn is not None:
            try:
                self._local.conn.close()
            except Exception as e:
                logger.debug("Error closing local connection: %s", e)
            self._local.conn = None
        with self._pool_lock:
            for conn in self._pool:
                try:
                    conn.close()
                except Exception as e:
                    logger.debug("Error closing pool connection: %s", e)
            self._pool.clear()
        with self._read_pool_lock:
            for conn in self._read_pool:
                try:
                    conn.close()
                except Exception as e:
                    logger.debug("Error closing read pool connection: %s", e)
            self._read_pool.clear()


_db_instance: SQLiteStore | None = None
_db_lock = threading.Lock()


class AsyncWriteQueue:
    def __init__(self, db: SQLiteStore, max_size: int = 1000, batch_size: int = 100):
        self._db = db
        self._queue: asyncio.Queue[tuple[str, tuple]] = asyncio.Queue(maxsize=max_size)
        self._batch_size = batch_size
        self._running = False
        self._task: asyncio.Task | None = None
        self._pending = 0

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            await self._task
            self._task = None

    async def put(self, sql: str, params: tuple = ()) -> None:
        self._pending += 1
        await self._queue.put((sql, params))

    def put_nowait(self, sql: str, params: tuple = ()) -> None:
        self._pending += 1
        self._queue.put_nowait((sql, params))

    @property
    def pending(self) -> int:
        return self._pending

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    async def _worker(self) -> None:
        batch: list[tuple[str, tuple]] = []
        while self._running or not self._queue.empty():
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                batch.append(item)
                while not self._queue.empty() and len(batch) < self._batch_size:
                    batch.append(self._queue.get_nowait())
                if batch:
                    await asyncio.to_thread(self._db._batch_execute, batch)
                    self._pending -= len(batch)
                    batch.clear()
            except asyncio.TimeoutError:
                if batch:
                    await asyncio.to_thread(self._db._batch_execute, batch)
                    self._pending -= len(batch)
                    batch.clear()
            except asyncio.CancelledError:
                if batch:
                    await asyncio.to_thread(self._db._batch_execute, batch)
                    self._pending -= len(batch)
                    batch.clear()
                return
            except Exception as e:
                logger.error("AsyncWriteQueue worker error: %s", e)
                if batch:
                    for sql, params in batch:
                        self._db.buffered_write(sql, params)
                    self._pending -= len(batch)
                    batch.clear()


def get_db() -> SQLiteStore:
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                _db_instance = SQLiteStore()
    return _db_instance


class AsyncDatabaseSession:
    """异步数据库会话上下文管理器

    提供异步友好的数据库访问接口，支持 async with 语法

    Usage:
        async with AsyncDatabaseSession() as session:
            result = await session.fetch_one("SELECT * FROM config WHERE key = ?", ("api_key",))
    """

    def __init__(self, db: SQLiteStore | None = None):
        self._db = db or get_db()
        self._conn = None

    async def __aenter__(self) -> 'AsyncDatabaseSession':
        def _get() -> sqlite3.Connection:
            return self._db._get_conn()
        loop = asyncio.get_running_loop()
        self._conn = await loop.run_in_executor(None, _get)  # type: ignore[arg-type,func-returns-value]
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn:
            try:
                if exc_type is None:
                    await asyncio.to_thread(self._conn.commit)
                else:
                    await asyncio.to_thread(self._conn.rollback)
            except Exception as e:
                logger.debug("Error in async session exit: %s", e)
            finally:
                try:
                    await asyncio.to_thread(self._db._release_to_pool, self._conn)
                except Exception as e:
                    logger.debug("Error releasing connection: %s", e)

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        """异步查询单条记录"""
        assert self._conn is not None
        def _fetch() -> dict | None:
            cursor = self._conn.execute(sql, params)
            row = cursor.fetchone()
            return dict(row) if row else None
        return await asyncio.to_thread(_fetch)

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        """异步查询多条记录"""
        assert self._conn is not None
        def _fetch() -> list[dict]:
            cursor = self._conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        return await asyncio.to_thread(_fetch)

    async def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """异步执行SQL"""
        assert self._conn is not None
        def _exec() -> sqlite3.Cursor:
            return self._conn.execute(sql, params)
        return await asyncio.to_thread(_exec)

    async def executemany(self, sql: str, params_list: list[tuple]) -> sqlite3.Cursor:
        """异步批量执行SQL"""
        assert self._conn is not None
        def _exec_many() -> sqlite3.Cursor:
            return self._conn.executemany(sql, params_list)
        return await asyncio.to_thread(_exec_many)
