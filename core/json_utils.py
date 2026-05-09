from __future__ import annotations

from typing import Any

try:
    import orjson

    _HAS_ORJSON = True
except ImportError:
    _HAS_ORJSON = False

__all__ = ["json_dumps", "json_loads"]


def json_dumps(obj: Any) -> str:
    if _HAS_ORJSON:
        return orjson.dumps(obj, option=orjson.OPT_NON_STR_KEYS).decode("utf-8")
    import json

    return json.dumps(obj, ensure_ascii=False, default=str)


def json_loads(obj: str | bytes) -> Any:
    if _HAS_ORJSON:
        return orjson.loads(obj)
    import json

    return json.loads(obj)
