import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.data_bundle_cache import DataBundleCache, CacheEntry, CacheMetadata


@pytest.fixture
def cache_dir(tmp_path):
    d = tmp_path / "test_cache"
    d.mkdir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_df(n: int = 100, start: str = "2023-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(42)
    dates = pd.date_range(start, periods=n, freq="B")
    close = np.cumsum(rng.normal(0.05, 1.0, n)) + 100
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": close - 0.3,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": rng.integers(1000, 10000, n),
    })


class TestCacheMetadata:

    def test_round_trip(self):
        meta = CacheMetadata(created_at=time.time())
        entry = CacheEntry(
            symbol="TEST", start_date="2023-01-01", end_date="2023-06-01",
            rows=100, columns=["date", "close"], file_path="TEST.parquet",
            last_updated=time.time(), source="test",
        )
        meta.entries["TEST"] = entry
        data = meta.to_dict()
        restored = CacheMetadata.from_dict(data)
        assert "TEST" in restored.entries
        assert restored.entries["TEST"].rows == 100

    def test_empty_metadata(self):
        data = {}
        meta = CacheMetadata.from_dict(data)
        assert len(meta.entries) == 0


class TestDataBundleCache:

    def test_put_and_get(self, cache_dir):
        cache = DataBundleCache(cache_dir)
        df = _make_df(50)
        entry = cache.put("TEST", df, source="test")
        assert isinstance(entry, CacheEntry)
        assert entry.rows == 50

        result = cache.get("TEST")
        assert result is not None
        assert len(result) == 50

    def test_get_nonexistent(self, cache_dir):
        cache = DataBundleCache(cache_dir)
        assert cache.get("NONEXISTENT") is None

    def test_get_with_date_filter(self, cache_dir):
        cache = DataBundleCache(cache_dir)
        df = _make_df(100)
        cache.put("TEST", df)
        result = cache.get("TEST", start_date="2023-03-01", end_date="2023-04-01")
        assert result is not None
        assert len(result) < 100

    def test_invalidate(self, cache_dir):
        cache = DataBundleCache(cache_dir)
        df = _make_df(50)
        cache.put("TEST", df)
        assert cache.invalidate("TEST") is True
        assert cache.get("TEST") is None

    def test_invalidate_nonexistent(self, cache_dir):
        cache = DataBundleCache(cache_dir)
        assert cache.invalidate("NONEXISTENT") is False

    def test_invalidate_all(self, cache_dir):
        cache = DataBundleCache(cache_dir)
        cache.put("A", _make_df(20))
        cache.put("B", _make_df(30))
        count = cache.invalidate_all()
        assert count == 2
        assert cache.get("A") is None
        assert cache.get("B") is None

    def test_list_entries(self, cache_dir):
        cache = DataBundleCache(cache_dir)
        cache.put("A", _make_df(20))
        cache.put("B", _make_df(30))
        entries = cache.list_entries()
        assert len(entries) == 2

    def test_get_stats(self, cache_dir):
        cache = DataBundleCache(cache_dir)
        cache.put("TEST", _make_df(50))
        stats = cache.get_stats()
        assert stats["n_entries"] == 1
        assert stats["total_size_bytes"] > 0
        assert stats["total_size_mb"] > 0

    def test_stale_entry(self, cache_dir):
        cache = DataBundleCache(cache_dir, max_age_hours=0.00001)
        df = _make_df(50)
        cache.put("TEST", df)
        time.sleep(1)
        result = cache.get("TEST")
        assert result is None

    def test_no_max_age(self, cache_dir):
        cache = DataBundleCache(cache_dir, max_age_hours=0)
        df = _make_df(50)
        cache.put("TEST", df)
        result = cache.get("TEST")
        assert result is not None

    def test_update_incremental_append(self, cache_dir):
        cache = DataBundleCache(cache_dir)
        df1 = _make_df(50, start="2023-01-01")
        cache.put("TEST", df1)
        df2 = _make_df(20, start="2023-03-15")
        entry = cache.update_incremental("TEST", df2)
        assert entry.rows >= 50

    def test_update_incremental_overlap(self, cache_dir):
        cache = DataBundleCache(cache_dir)
        df1 = _make_df(50, start="2023-01-01")
        cache.put("TEST", df1)
        df2 = _make_df(50, start="2023-02-01")
        entry = cache.update_incremental("TEST", df2)
        assert entry.rows >= 50

    def test_update_incremental_no_existing(self, cache_dir):
        cache = DataBundleCache(cache_dir)
        df = _make_df(50)
        entry = cache.update_incremental("NEW", df)
        assert entry.rows == 50

    def test_metadata_persists(self, cache_dir):
        cache1 = DataBundleCache(cache_dir)
        cache1.put("TEST", _make_df(50))
        cache2 = DataBundleCache(cache_dir)
        result = cache2.get("TEST")
        assert result is not None
        assert len(result) == 50
