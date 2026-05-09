import time
from unittest.mock import MagicMock, patch

import pytest

from core.memory_guard import (
    _CLEANUP_CALLBACKS,
    MemoryGuard,
    check_and_reclaim_if_needed,
    limit_cache_size,
    memory_guard,
    reclaim_memory,
    register_cleanup,
)


@pytest.fixture(autouse=True)
def _reset_module_state():
    _CLEANUP_CALLBACKS.clear()
    import core.memory_guard as mg
    mg._LAST_GC_TIME = 0.0
    yield
    _CLEANUP_CALLBACKS.clear()
    mg._LAST_GC_TIME = 0.0


def _make_psutil_mock(rss=100 * 1024 ** 2, vms=200 * 1024 ** 2,
                      total=16 * 1024 ** 3, available=8 * 1024 ** 3,
                      percent=50.0):
    process_mock = MagicMock()
    process_mock.memory_info.return_value = MagicMock(rss=rss, vms=vms)
    vm_mock = MagicMock(total=total, available=available, percent=percent)
    psutil_mock = MagicMock()
    psutil_mock.Process.return_value = process_mock
    psutil_mock.virtual_memory.return_value = vm_mock
    return psutil_mock


class TestGetMemoryUsage:
    @patch("core.memory_guard.psutil", create=True)
    def test_returns_dict_with_expected_keys(self, _):
        import core.memory_guard as mg
        with patch.dict("sys.modules", {"psutil": _make_psutil_mock()}):
            result = mg.get_memory_usage()
        expected_keys = {
            "rss_mb", "vms_mb", "system_total_gb",
            "system_available_gb", "system_used_pct", "process_pct",
        }
        assert isinstance(result, dict)
        assert expected_keys.issubset(result.keys())

    @patch("core.memory_guard.psutil", create=True)
    def test_values_are_numeric(self, _):
        import core.memory_guard as mg
        with patch.dict("sys.modules", {"psutil": _make_psutil_mock()}):
            result = mg.get_memory_usage()
        for key in ("rss_mb", "vms_mb", "system_total_gb",
                     "system_available_gb", "system_used_pct", "process_pct"):
            assert isinstance(result[key], (int, float)), f"{key} should be numeric"


class TestIsMemoryPressure:
    @patch("core.memory_guard.psutil", create=True)
    def test_returns_true_when_above_threshold(self, _):
        import core.memory_guard as mg
        threshold = mg._ADAPTIVE["pressure"] * 100
        mock_psutil = _make_psutil_mock(percent=threshold + 1)
        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            assert mg.is_memory_pressure() is True

    @patch("core.memory_guard.psutil", create=True)
    def test_returns_false_when_below_threshold(self, _):
        import core.memory_guard as mg
        threshold = mg._ADAPTIVE["pressure"] * 100
        mock_psutil = _make_psutil_mock(percent=threshold - 10)
        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            assert mg.is_memory_pressure() is False


class TestIsMemoryCritical:
    @patch("core.memory_guard.psutil", create=True)
    def test_returns_true_when_above_threshold(self, _):
        import core.memory_guard as mg
        threshold = mg._ADAPTIVE["critical"] * 100
        mock_psutil = _make_psutil_mock(percent=threshold + 1)
        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            assert mg.is_memory_critical() is True

    @patch("core.memory_guard.psutil", create=True)
    def test_returns_false_when_below_threshold(self, _):
        import core.memory_guard as mg
        threshold = mg._ADAPTIVE["critical"] * 100
        mock_psutil = _make_psutil_mock(percent=threshold - 10)
        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            assert mg.is_memory_critical() is False


class TestRegisterCleanup:
    def test_callback_is_called_during_reclaim(self):
        cb = MagicMock()
        register_cleanup(cb)
        with patch("core.memory_guard.get_memory_usage", return_value={"rss_mb": 100}):
            result = reclaim_memory(force=True)
        assert result is True
        cb.assert_called_once()


class TestReclaimMemory:
    def test_respects_cooldown(self):
        import core.memory_guard as mg
        with patch("core.memory_guard.get_memory_usage", return_value={"rss_mb": 100}):
            reclaim_memory(force=True)
        mg._LAST_GC_TIME = time.time()
        result = reclaim_memory(force=False)
        assert result is False

    def test_force_bypasses_cooldown(self):
        import core.memory_guard as mg
        with patch("core.memory_guard.get_memory_usage", return_value={"rss_mb": 100}):
            reclaim_memory(force=True)
        mg._LAST_GC_TIME = time.time()
        result = reclaim_memory(force=True)
        assert result is True


class TestCheckAndReclaimIfNeeded:
    @patch("core.memory_guard.is_memory_critical", return_value=True)
    @patch("core.memory_guard.reclaim_memory", return_value=True)
    def test_forces_reclaim_on_critical(self, mock_reclaim, _mock_crit):
        result = check_and_reclaim_if_needed()
        assert result is True
        mock_reclaim.assert_called_once_with(force=True)

    @patch("core.memory_guard.is_memory_critical", return_value=False)
    @patch("core.memory_guard.is_memory_pressure", return_value=False)
    def test_returns_false_when_no_pressure(self, _mock_press, _mock_crit):
        result = check_and_reclaim_if_needed()
        assert result is False


class TestMemoryGuardContextManager:
    @patch("core.memory_guard.check_and_reclaim_if_needed", return_value=False)
    @patch("core.memory_guard.get_memory_usage", return_value={"rss_mb": 100})
    def test_basic_usage(self, _mock_mem, _mock_reclaim):
        with memory_guard("test_op", max_mb=2048):
            pass
        _mock_reclaim.assert_called_once()

    @patch("core.memory_guard.get_memory_usage", return_value={"rss_mb": 3000})
    @patch("core.memory_guard.check_and_reclaim_if_needed", return_value=False)
    @patch("core.memory_guard.reclaim_memory", return_value=True)
    def test_auto_reclaim_when_over_limit(self, mock_reclaim, _mock_check, _mock_mem):
        with memory_guard("test_op", max_mb=2048, auto_reclaim=False):
            pass
        mock_reclaim.assert_called_with(force=True)


class TestMemoryGuardClass:
    @patch("core.memory_guard.check_and_reclaim_if_needed", return_value=False)
    @patch("core.memory_guard.get_memory_usage", return_value={"rss_mb": 100})
    def test_basic_usage_as_context_manager(self, _mock_mem, _mock_reclaim):
        with MemoryGuard("test_op", max_mb=2048):
            pass
        _mock_reclaim.assert_called_once()


class TestLimitCacheSize:
    def test_trims_dict_and_returns_removal_count(self):
        cache = {i: f"val_{i}" for i in range(10)}
        removed = limit_cache_size(cache, max_size=5)
        assert removed == 5
        assert len(cache) == 5

    def test_no_trim_when_under_limit(self):
        cache = {i: f"val_{i}" for i in range(3)}
        removed = limit_cache_size(cache, max_size=10)
        assert removed == 0
        assert len(cache) == 3

    def test_removes_oldest_keys_first(self):
        cache = {}
        for i in range(5):
            cache[f"key_{i}"] = i
        removed = limit_cache_size(cache, max_size=3)
        assert removed == 2
        assert "key_0" not in cache
        assert "key_1" not in cache
        assert "key_3" in cache
        assert "key_4" in cache
