__all__ = [
    "DataBundleCache",
    "CacheEntry",
    "CacheMetadata",
]

import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_METADATA_FILE = "_cache_metadata.json"


@dataclass
class CacheEntry:
    symbol: str
    start_date: str
    end_date: str
    rows: int
    columns: list[str]
    file_path: str
    last_updated: float = 0.0
    source: str = ""


@dataclass
class CacheMetadata:
    entries: dict[str, CacheEntry] = field(default_factory=dict)
    version: str = "1.0"
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "entries": {
                sym: {
                    "symbol": e.symbol,
                    "start_date": e.start_date,
                    "end_date": e.end_date,
                    "rows": e.rows,
                    "columns": e.columns,
                    "file_path": e.file_path,
                    "last_updated": e.last_updated,
                    "source": e.source,
                }
                for sym, e in self.entries.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CacheMetadata":
        entries = {}
        for sym, ed in data.get("entries", {}).items():
            entries[sym] = CacheEntry(
                symbol=ed["symbol"],
                start_date=ed["start_date"],
                end_date=ed["end_date"],
                rows=ed["rows"],
                columns=ed["columns"],
                file_path=ed["file_path"],
                last_updated=ed.get("last_updated", 0.0),
                source=ed.get("source", ""),
            )
        return cls(
            entries=entries,
            version=data.get("version", "1.0"),
            created_at=data.get("created_at", 0.0),
        )


class DataBundleCache:
    def __init__(
        self,
        cache_dir: str | Path,
        max_age_hours: float = 24.0,
        compression: str = "snappy",
    ):
        self._cache_dir = Path(cache_dir)
        self._max_age_seconds = max_age_hours * 3600
        self._compression = compression
        self._metadata = CacheMetadata(created_at=time.time())
        self._load_metadata()

    def _load_metadata(self) -> None:
        meta_path = self._cache_dir / _METADATA_FILE
        if meta_path.exists():
            try:
                with open(meta_path) as f:
                    data = json.load(f)
                self._metadata = CacheMetadata.from_dict(data)
            except (json.JSONDecodeError, KeyError, OSError) as e:
                logger.debug("Failed to load cache metadata: %s", e)
                self._metadata = CacheMetadata(created_at=time.time())

    def _save_metadata(self) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        meta_path = self._cache_dir / _METADATA_FILE
        try:
            with open(meta_path, "w") as f:
                json.dump(self._metadata.to_dict(), f, indent=2, default=str)
        except OSError as e:
            logger.warning("Failed to save cache metadata: %s", e)

    def get(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame | None:
        entry = self._metadata.entries.get(symbol)
        if entry is None:
            return None

        file_path = self._cache_dir / entry.file_path
        if not file_path.exists():
            logger.debug("Cache file missing for %s: %s", symbol, file_path)
            self._metadata.entries.pop(symbol, None)
            return None

        if self._is_stale(entry):
            logger.debug("Cache entry stale for %s", symbol)
            return None

        try:
            df = pd.read_parquet(file_path)
        except Exception as e:
            logger.debug("Failed to read cache for %s: %s", symbol, e)
            return None

        if start_date and "date" in df.columns:
            df = df[df["date"] >= start_date].copy()
        if end_date and "date" in df.columns:
            df = df[df["date"] <= end_date].copy()

        return df

    def put(
        self,
        symbol: str,
        df: pd.DataFrame,
        source: str = "",
    ) -> CacheEntry:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{symbol}.parquet"
        file_path = self._cache_dir / file_name

        try:
            df.to_parquet(file_path, compression=self._compression, index=False)
        except Exception as e:
            logger.warning("Failed to write cache for %s: %s", symbol, e)
            raise

        start_date = ""
        end_date = ""
        if "date" in df.columns:
            dates = pd.to_datetime(df["date"], errors="coerce")
            start_date = str(dates.min())[:10] if dates.notna().any() else ""
            end_date = str(dates.max())[:10] if dates.notna().any() else ""

        entry = CacheEntry(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            rows=len(df),
            columns=list(df.columns),
            file_path=file_name,
            last_updated=time.time(),
            source=source,
        )
        self._metadata.entries[symbol] = entry
        self._save_metadata()
        return entry

    def invalidate(self, symbol: str) -> bool:
        entry = self._metadata.entries.pop(symbol, None)
        if entry is None:
            return False
        file_path = self._cache_dir / entry.file_path
        if file_path.exists():
            with contextlib.suppress(OSError):
                file_path.unlink()
        self._save_metadata()
        return True

    def invalidate_all(self) -> int:
        count = 0
        for symbol in list(self._metadata.entries.keys()):
            if self.invalidate(symbol):
                count += 1
        return count

    def list_entries(self) -> list[CacheEntry]:
        return list(self._metadata.entries.values())

    def get_stats(self) -> dict[str, Any]:
        total_size = 0
        for entry in self._metadata.entries.values():
            file_path = self._cache_dir / entry.file_path
            if file_path.exists():
                total_size += file_path.stat().st_size
        return {
            "n_entries": len(self._metadata.entries),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "cache_dir": str(self._cache_dir),
            "max_age_hours": round(self._max_age_seconds / 3600, 2),
        }

    def _is_stale(self, entry: CacheEntry) -> bool:
        if self._max_age_seconds <= 0:
            return False
        age = time.time() - entry.last_updated
        return age > self._max_age_seconds

    def update_incremental(
        self,
        symbol: str,
        new_df: pd.DataFrame,
        source: str = "",
    ) -> CacheEntry:
        existing = self.get(symbol)
        if existing is None or existing.empty:
            return self.put(symbol, new_df, source=source)

        if "date" not in existing.columns or "date" not in new_df.columns:
            return self.put(symbol, new_df, source=source)

        existing["date"] = pd.to_datetime(existing["date"], errors="coerce")
        new_df = new_df.copy()
        new_df["date"] = pd.to_datetime(new_df["date"], errors="coerce")

        existing_end = existing["date"].max()
        new_start = new_df["date"].min()

        if pd.isna(existing_end) or pd.isna(new_start):
            return self.put(symbol, new_df, source=source)

        if new_start > existing_end:
            combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["date"], keep="last")

        combined = combined.sort_values("date").reset_index(drop=True)
        combined["date"] = combined["date"].dt.strftime("%Y-%m-%d")
        return self.put(symbol, combined, source=source)
