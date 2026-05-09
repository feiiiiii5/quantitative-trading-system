import asyncio
import os
import tempfile
from unittest.mock import patch

import pytest

from core.database import AsyncWriteQueue, SQLiteStore


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    store = SQLiteStore(path)
    yield store
    store.close()
    os.unlink(path)


class TestAsyncWriteQueueInit:
    def test_init_defaults(self, db: SQLiteStore) -> None:
        queue = AsyncWriteQueue(db)
        assert queue._batch_size == 100
        assert queue._queue.maxsize == 1000
        assert queue._running is False

    def test_init_custom(self, db: SQLiteStore) -> None:
        queue = AsyncWriteQueue(db, max_size=500, batch_size=25)
        assert queue._queue.maxsize == 500
        assert queue._batch_size == 25

    def test_pending_initial_zero(self, db: SQLiteStore) -> None:
        queue = AsyncWriteQueue(db)
        assert queue.pending == 0

    def test_qsize_initial_zero(self, db: SQLiteStore) -> None:
        queue = AsyncWriteQueue(db)
        assert queue.qsize == 0


class TestAsyncWriteQueuePut:
    @pytest.mark.asyncio
    async def test_put_increments_pending(self, db: SQLiteStore) -> None:
        queue = AsyncWriteQueue(db)
        await queue.put("INSERT INTO config (key, value) VALUES (?, ?)", ("k1", "v1"))
        assert queue.pending == 1
        assert queue.qsize == 1

    @pytest.mark.asyncio
    async def test_put_nowait(self, db: SQLiteStore) -> None:
        queue = AsyncWriteQueue(db)
        queue.put_nowait("INSERT INTO config (key, value) VALUES (?, ?)", ("k2", "v2"))
        assert queue.pending == 1
        assert queue.qsize == 1


class TestAsyncWriteQueueLifecycle:
    @pytest.mark.asyncio
    async def test_start_sets_running(self, db: SQLiteStore) -> None:
        queue = AsyncWriteQueue(db)
        await queue.start()
        assert queue._running is True
        await queue.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self, db: SQLiteStore) -> None:
        queue = AsyncWriteQueue(db)
        await queue.start()
        await queue.stop()
        assert queue._running is False


class TestAsyncWriteQueueWorker:
    @pytest.mark.asyncio
    async def test_worker_processes_items(self, db: SQLiteStore) -> None:
        queue = AsyncWriteQueue(db)
        for i in range(5):
            await queue.put("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (f"wk_key_{i}", f"wk_val_{i}"))
        with patch.object(db, "_batch_execute", wraps=db._batch_execute) as mock_batch:
            await queue.start()
            for _ in range(50):
                if queue.pending == 0:
                    break
                await asyncio.sleep(0.05)
            await queue.stop()
        assert mock_batch.called
        assert queue.pending == 0

    @pytest.mark.asyncio
    async def test_worker_batches_items(self, db: SQLiteStore) -> None:
        queue = AsyncWriteQueue(db, batch_size=50)
        for i in range(150):
            await queue.put("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (f"bt_key_{i}", f"bt_val_{i}"))
        with patch.object(db, "_batch_execute", wraps=db._batch_execute) as mock_batch:
            await queue.start()
            for _ in range(100):
                if queue.pending == 0:
                    break
                await asyncio.sleep(0.05)
            await queue.stop()
        assert mock_batch.call_count >= 3
        batch_sizes = [len(call.args[0]) for call in mock_batch.call_args_list]
        for size in batch_sizes:
            assert size <= 50

    @pytest.mark.asyncio
    async def test_worker_fallback_on_error(self, db: SQLiteStore) -> None:
        queue = AsyncWriteQueue(db)
        for i in range(3):
            await queue.put("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (f"fb_key_{i}", f"fb_val_{i}"))
        with patch.object(db, "_batch_execute", side_effect=Exception("forced failure")):
            with patch.object(db, "buffered_write", wraps=db.buffered_write) as mock_bw:
                await queue.start()
                for _ in range(50):
                    if queue.pending == 0:
                        break
                    await asyncio.sleep(0.05)
                await queue.stop()
        assert mock_bw.call_count == 3
        assert queue.pending == 0
