import gc
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from contextlib import contextmanager

logger = logging.getLogger(__name__)

__all__ = [
    'get_memory_usage',
    'is_memory_pressure',
    'is_memory_critical',
    'register_cleanup',
    'reclaim_memory',
    'check_and_reclaim_if_needed',
    'memory_guard',
    'MemoryGuard',
    'limit_cache_size',
    'get_adaptive_thresholds',
]

_MEMORY_WARNING_RATIO = 0.75
_MEMORY_CRITICAL_RATIO = 0.85
_LOCK = threading.Lock()
_LAST_GC_TIME = 0.0
_GC_COOLDOWN = 20.0
_MAX_CACHE_SIZE = 1000
_CLEANUP_CALLBACKS: list[Callable[[], None]] = []


def get_adaptive_thresholds() -> dict:
    try:
        import psutil
        total_gb = psutil.virtual_memory().total / (1024 ** 3)
        if total_gb >= 16:
            return {"pressure": 0.75, "critical": 0.90, "max_backtest_mb": 4096}
        elif total_gb >= 8:
            return {"pressure": 0.70, "critical": 0.85, "max_backtest_mb": 2048}
        else:
            return {"pressure": 0.65, "critical": 0.80, "max_backtest_mb": 1024}
    except ImportError:
        return {"pressure": 0.70, "critical": 0.85, "max_backtest_mb": 2048}


_ADAPTIVE = get_adaptive_thresholds()


def get_memory_usage() -> dict:
    """获取当前进程内存使用情况"""
    try:
        import psutil
        process = psutil.Process()
        mem_info = process.memory_info()
        system_mem = psutil.virtual_memory()
        return {
            "rss_mb": round(mem_info.rss / 1024 ** 2, 1),
            "vms_mb": round(mem_info.vms / 1024 ** 2, 1),
            "system_total_gb": round(system_mem.total / 1024 ** 3, 1),
            "system_available_gb": round(system_mem.available / 1024 ** 3, 1),
            "system_used_pct": round(system_mem.percent, 1),
            "process_pct": round(mem_info.rss / system_mem.total * 100, 1),
        }
    except ImportError:
        return {"rss_mb": 0, "system_used_pct": 0, "process_pct": 0}


def is_memory_pressure() -> bool:
    try:
        import psutil
        return bool(psutil.virtual_memory().percent >= _ADAPTIVE["pressure"] * 100)
    except ImportError:
        return False


def is_memory_critical() -> bool:
    try:
        import psutil
        return bool(psutil.virtual_memory().percent >= _ADAPTIVE["critical"] * 100)
    except ImportError:
        return False


def register_cleanup(callback: Callable[[], None]) -> None:
    _CLEANUP_CALLBACKS.append(callback)


def reclaim_memory(force: bool = False) -> bool:
    global _LAST_GC_TIME

    with _LOCK:
        now = time.time()
        if not force and (now - _LAST_GC_TIME) < _GC_COOLDOWN:
            return False

        before = get_memory_usage().get("rss_mb", 0)

        for cb in _CLEANUP_CALLBACKS:
            try:
                cb()
            except Exception as e:
                logger.warning("缓存清理回调失败: %s", e)

        gc.collect()

        _LAST_GC_TIME = time.time()

        after = get_memory_usage().get("rss_mb", 0)
        freed = before - after
        if freed > 1:
            logger.info("内存回收完成: %sMB → %sMB (释放 %sMB)", before, after, freed)

    return True


def check_and_reclaim_if_needed() -> bool:
    """检查内存状态，在压力时自动回收

    Returns:
        是否执行了回收操作
    """
    if is_memory_critical():
        logger.warning("内存使用达到临界水平，执行强制回收")
        return reclaim_memory(force=True)
    if is_memory_pressure():
        logger.info("内存压力较高，执行缓存回收")
        return reclaim_memory(force=False)
    return False


@contextmanager
def memory_guard(operation: str = "", max_mb: int | None = None, auto_reclaim: bool = True):
    if max_mb is None:
        max_mb = _ADAPTIVE["max_backtest_mb"]
    start_mb = get_memory_usage().get("rss_mb", 0)
    if start_mb > max_mb:
        logger.warning(
            "[%s] 内存已超限 %.0fMB > %dMB，执行预回收",
            operation, start_mb, max_mb,
        )
        reclaim_memory(force=True)
        start_mb = get_memory_usage().get("rss_mb", 0)

    try:
        yield
    finally:
        if auto_reclaim:
            end_mb = get_memory_usage().get("rss_mb", 0)
            delta = end_mb - start_mb
            if delta > 500:
                logger.warning(
                    "[%s] 内存增长 %.0fMB (当前 %.0fMB)，建议检查内存泄漏",
                    operation, delta, end_mb,
                )
            check_and_reclaim_if_needed()


class MemoryGuard:
    def __init__(self, operation: str = "", max_mb: int | None = None):
        self._operation = operation
        self._max_mb = max_mb or _ADAPTIVE["max_backtest_mb"]
        self._start_mb = 0.0

    def __enter__(self):
        self._start_mb = get_memory_usage().get("rss_mb", 0)
        if self._start_mb > self._max_mb:
            logger.warning(
                "[%s] 内存已超限 %.0fMB > %dMB，执行回收",
                self._operation, self._start_mb, self._max_mb,
            )
            reclaim_memory(force=True)
            self._start_mb = get_memory_usage().get("rss_mb", 0)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        end_mb = get_memory_usage().get("rss_mb", 0)
        delta = end_mb - self._start_mb
        if delta > 500:
            logger.warning(
                "[%s] 内存增长 %.0fMB (当前 %.0fMB)，建议检查内存泄漏",
                self._operation, delta, end_mb,
            )
        check_and_reclaim_if_needed()
        return False


def limit_cache_size(cache_dict: dict, max_size: int | None = None) -> int:
    """限制缓存字典大小，自动清理最旧的条目

    Args:
        cache_dict: 缓存字典（应为OrderedDict或Python 3.7+ dict以保持插入顺序）
        max_size: 最大条目数，默认为_MAX_CACHE_SIZE

    Returns:
        清理的条目数量
    """
    max_size = max_size or _MAX_CACHE_SIZE
    if len(cache_dict) <= max_size:
        return 0

    if not isinstance(cache_dict, (dict, OrderedDict)):
        logger.warning("limit_cache_size: cache_dict is not a dict type: %s", type)
        return 0

    to_remove = len(cache_dict) - max_size
    removed = 0
    keys_to_remove = list(cache_dict.keys())[:to_remove]

    for key in keys_to_remove:
        try:
            del cache_dict[key]
            removed += 1
        except KeyError:
            logger.debug("limit_cache_size: key %s not found during cleanup", key)

    if removed > 0:
        logger.debug("缓存清理: 移除 %s 个旧条目", removed)
    return removed
