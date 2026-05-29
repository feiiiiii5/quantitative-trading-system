import asyncio
import logging
import re
import threading
import time
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from functools import wraps

import numpy as np
import orjson
from fastapi.responses import Response

logger = logging.getLogger(__name__)

_SYMBOL_RE = re.compile(r"^[0-9a-zA-Z\.]{1,20}$")
_MARKET_RE = re.compile(r"^[A-Z]{1,3}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_INTERNAL_PATTERNS = [
    re.compile(r"(?:Traceback|File \").*?(?=\n|$)", re.DOTALL),
    re.compile(r"/(?:Users|home|tmp|var)/\S+"),
    re.compile(r"(?:SELECT|INSERT|UPDATE|DELETE|CREATE)\s+", re.IGNORECASE),
    re.compile(r"(?:password|secret|token|api_key|apikey)\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"sqlite3\.\w+Error:.*", re.IGNORECASE),
]


def validate_symbol(symbol: str) -> bool:
    if not isinstance(symbol, str):
        return False
    return bool(_SYMBOL_RE.match(symbol))


def validate_market(market: str) -> bool:
    if not isinstance(market, str):
        return False
    return bool(_MARKET_RE.match(market))


def validate_date(date_str: str) -> bool:
    if not isinstance(date_str, str):
        return False
    if not _DATE_RE.match(date_str):
        return False
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def validate_price(price: float) -> bool:
    if not isinstance(price, (int, float)):
        return False
    return 0 < price < 1e9


def validate_percentage(pct: float, min_val: float = 0.0, max_val: float = 1.0) -> bool:
    if not isinstance(pct, (int, float)):
        return False
    return min_val <= pct <= max_val


def safe_error(exc: Exception) -> str:
    msg = str(exc)
    if len(msg) > 200:
        msg = msg[:200] + "..."
    for pat in _INTERNAL_PATTERNS:
        msg = pat.sub("[internal]", msg)
    return msg


def period_to_history(period: str) -> str:
    period = (period or "1y").lower()
    if period in {"3m", "6m"}:
        return "1y"
    if period in {"3y", "5y", "all"}:
        return "all"
    return "1y"


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


def get_trading(request) -> object | None:
    trading = getattr(request.app.state, "trading", None)
    return trading


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
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, set):
        return [sanitize(v, _depth + 1) for v in obj]
    if isinstance(obj, dict):
        return {k: sanitize(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v, _depth + 1) for v in obj]
    return obj


def json_response(success: bool, data=None, error: str = ""):
    return orjson_response(success, data, error)


def orjson_response(success: bool, data=None, error: str = "", status_code: int = 200) -> Response:
    from api.middleware import correlation_id
    payload = {"success": success, "data": sanitize(data), "error": error}
    cid = correlation_id.get("")
    if cid:
        payload["request_id"] = cid
    body = orjson.dumps(payload, default=_orjson_default)
    return Response(content=body, status_code=status_code, media_type="application/json")


def _orjson_default(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, set):
        return list(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def api_error_handler(
    func: Callable | None = None,
    *,
    catch_exceptions: tuple[type[Exception], ...] = (Exception,),
    log_errors: bool = True,
    timeout: float | None = None,
):
    """
    Decorator for unified API error handling.

    Args:
        func: The function to decorate
        catch_exceptions: Tuple of exception types to catch
        log_errors: Whether to log errors
        timeout: Optional timeout in seconds for async functions

    Returns:
        Decorated function with error handling
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def async_wrapper(*args, **kwargs):
            start_time = time.monotonic()
            try:
                if timeout:
                    result = await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)
                else:
                    result = await fn(*args, **kwargs)
                return result
            except TimeoutError:
                if log_errors:
                    logger.error("API timeout after %ss: %s", timeout, fn)
                return json_response(False, error="请求超时")
            except catch_exceptions as e:
                if log_errors:
                    logger.error("API error in %s: %s", fn, e,  exc_info=True)
                return json_response(False, error=safe_error(e))
            finally:
                elapsed = time.monotonic() - start_time
                if elapsed > 5.0:
                    logger.warning("Slow API call: %s took %ss", fn, elapsed)

        @wraps(fn)
        def sync_wrapper(*args, **kwargs):
            start_time = time.monotonic()
            try:
                result = fn(*args, **kwargs)
                return result
            except catch_exceptions as e:
                if log_errors:
                    logger.error("API error in %s: %s", fn, e,  exc_info=True)
                return json_response(False, error=safe_error(e))
            finally:
                elapsed = time.monotonic() - start_time
                if elapsed > 5.0:
                    logger.warning("Slow API call: %s took %ss", fn, elapsed)

        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return sync_wrapper

    if func:
        return decorator(func)
    return decorator


def validate_request(**validators):
    """
    Decorator to validate request parameters.

    Args:
        validators: Keyword arguments mapping parameter names to validation functions

    Example:
        @validate_request(symbol=validate_symbol, market=validate_market)
        async def get_stock_data(symbol: str, market: str = "A"):
            ...
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def async_wrapper(*args, **kwargs):
            for param_name, validator in validators.items():
                if param_name in kwargs and not validator(kwargs[param_name]):
                    return json_response(False, error=f"Invalid {param_name}: {kwargs[param_name]}")
            return await fn(*args, **kwargs)

        @wraps(fn)
        def sync_wrapper(*args, **kwargs):
            for param_name, validator in validators.items():
                if param_name in kwargs and not validator(kwargs[param_name]):
                    return json_response(False, error=f"Invalid {param_name}: {kwargs[param_name]}")
            return fn(*args, **kwargs)

        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return sync_wrapper

    return decorator


def rate_limiter(max_calls: int = 100, time_window: float = 60.0):
    """
    Simple rate limiter decorator.

    Args:
        max_calls: Maximum number of calls allowed
        time_window: Time window in seconds
    """
    call_timestamps = []
    _lock = threading.Lock()

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def async_wrapper(*args, **kwargs):
            nonlocal call_timestamps
            now = time.monotonic()
            with _lock:
                call_timestamps = [t for t in call_timestamps if now - t < time_window]
                if len(call_timestamps) >= max_calls:
                    return json_response(False, error="请求过于频繁，请稍后重试")
                call_timestamps.append(now)
            return await fn(*args, **kwargs)

        @wraps(fn)
        def sync_wrapper(*args, **kwargs):
            nonlocal call_timestamps
            now = time.monotonic()
            with _lock:
                call_timestamps = [t for t in call_timestamps if now - t < time_window]
                if len(call_timestamps) >= max_calls:
                    return json_response(False, error="请求过于频繁，请稍后重试")
                call_timestamps.append(now)
            return fn(*args, **kwargs)

        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return sync_wrapper

    return decorator
