import re

import numpy as np

_INTERNAL_PATTERNS = [
    re.compile(r"(?:Traceback|File \").*?(?=\n|$)", re.DOTALL),
    re.compile(r"/(?:Users|home|tmp|var)/\S+"),
    re.compile(r"(?:SELECT|INSERT|UPDATE|DELETE|CREATE)\s+", re.IGNORECASE),
]


def safe_error(exc: Exception) -> str:
    msg = str(exc)
    if len(msg) > 200:
        msg = msg[:200] + "..."
    for pat in _INTERNAL_PATTERNS:
        msg = pat.sub("[internal]", msg)
    return msg


def sanitize(obj, _depth: int = 0):
    if _depth > 10:
        return str(type(obj).__name__)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: sanitize(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v, _depth + 1) for v in obj]
    return obj


def json_response(success: bool, data=None, error: str = ""):
    return {"success": success, "data": sanitize(data), "error": error}
