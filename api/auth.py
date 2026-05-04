import hashlib
import hmac
import logging
import time
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}


class APIAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key: str = "", enabled: bool = False):
        super().__init__(app)
        self._api_key = api_key
        self._enabled = enabled
        if not enabled:
            logger.warning("API认证已禁用，所有接口公开可访问。生产环境请启用认证。")
        self._rate_limits: dict[str, list[float]] = {}
        self._rate_limit_per_minute = 120
        self._max_clients = 10000
        self._last_cleanup = time.time()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in _PUBLIC_PATHS:
            return await call_next(request)

        if path.startswith("/assets") or path.startswith("/static"):
            return await call_next(request)

        if path.startswith("/api"):
            if self._enabled and self._api_key:
                auth_header = request.headers.get("Authorization", "")
                api_key = request.headers.get("X-API-Key", "")

                if auth_header.startswith("Bearer "):
                    provided_key = auth_header[7:]
                elif api_key:
                    provided_key = api_key
                else:
                    provided_key = ""

                if not self._verify_key(provided_key):
                    logger.warning(f"API认证失败: {request.client.host if request.client else 'unknown'} -> {path}")
                    return JSONResponse(
                        status_code=401,
                        content={"success": False, "error": "未授权访问，请提供有效的API密钥"},
                    )

            client_id = self._get_client_id(request)
            if not self._check_rate_limit(client_id):
                return JSONResponse(
                    status_code=429,
                    content={"success": False, "error": "请求频率超限，请稍后重试"},
                )

        return await call_next(request)

    def _verify_key(self, provided_key: str) -> bool:
        if not provided_key or not self._api_key:
            return False
        return hmac.compare_digest(
            hashlib.sha256(provided_key.encode()).hexdigest(),
            hashlib.sha256(self._api_key.encode()).hexdigest(),
        )

    def _get_client_id(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return f"{request.client.host}"
        return "unknown"

    def _check_rate_limit(self, client_id: str) -> bool:
        now = time.time()
        if now - self._last_cleanup > 300:
            self._cleanup_stale_clients(now)
            self._last_cleanup = now

        if client_id not in self._rate_limits:
            if len(self._rate_limits) >= self._max_clients:
                self._cleanup_stale_clients(now)
            self._rate_limits[client_id] = [now]
            return True

        timestamps = self._rate_limits[client_id]
        timestamps = [t for t in timestamps if now - t < 60]
        timestamps.append(now)
        self._rate_limits[client_id] = timestamps

        if len(timestamps) > self._rate_limit_per_minute:
            return False
        return True

    def _cleanup_stale_clients(self, now: float) -> None:
        stale = [cid for cid, ts in self._rate_limits.items() if not ts or now - ts[-1] > 300]
        for cid in stale:
            del self._rate_limits[cid]
