import time

from api.routes import _TTLCache


class TestTTLCacheLFU:
    def test_basic_get_set(self):
        cache = _TTLCache(ttl=5.0, maxsize=10)
        cache.set("a", 1)
        assert cache.get("a") == 1
        assert cache.get("missing") is None

    def test_ttl_expiry(self):
        cache = _TTLCache(ttl=0.01, maxsize=10)
        cache.set("a", 1)
        time.sleep(0.02)
        assert cache.get("a") is None

    def test_lfu_eviction_prefers_high_freq(self):
        cache = _TTLCache(ttl=60.0, maxsize=3)
        cache.set("cold", 1)
        cache.set("warm", 2)
        cache.set("hot", 3)
        for _ in range(10):
            cache.get("hot")
        for _ in range(5):
            cache.get("warm")
        cache.set("new1", 4)
        assert cache.get("cold") is None
        assert cache.get("warm") == 2
        assert cache.get("hot") == 3

    def test_stale_freq_cleanup_on_evict(self):
        cache = _TTLCache(ttl=0.01, maxsize=3)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        time.sleep(0.02)
        cache.set("d", 4)
        assert cache.get("d") == 4

    def test_stats(self):
        cache = _TTLCache(ttl=60.0, maxsize=100)
        cache.set("a", 1)
        cache.set("b", 2)
        stats = cache.stats()
        assert stats["size"] == 2
        assert stats["maxsize"] == 100

    def test_clear(self):
        cache = _TTLCache(ttl=60.0, maxsize=10)
        cache.set("a", 1)
        cache.clear()
        assert cache.get("a") is None
        assert len(cache) == 0

    def test_freq_increments_on_hit(self):
        cache = _TTLCache(ttl=60.0, maxsize=10)
        cache.set("a", 1)
        cache.get("a")
        cache.get("a")
        cache.get("a")
        assert cache._freq["a"] == 4

    def test_expired_entry_cleans_freq(self):
        cache = _TTLCache(ttl=0.01, maxsize=10)
        cache.set("a", 1)
        cache.get("a")
        assert "a" in cache._freq
        time.sleep(0.02)
        cache.get("a")
        assert "a" not in cache._freq
