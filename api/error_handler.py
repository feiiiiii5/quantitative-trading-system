from __future__ import annotations

import logging
import traceback
import uuid

from starlette.requests import Request
from starlette.responses import JSONResponse

from api.errors import AppError, ErrorCode

logger = logging.getLogger(__name__)


class GlobalErrorHandler:
    async def __call__(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except AppError as exc:
            logger.warning("AppError: %s [%s]", exc.message, exc.error_code.code)
            return JSONResponse(
                content=exc.to_response(),
                status_code=exc.http_status,
            )
        except ValueError as exc:
            logger.warning("ValueError: %s", exc)
            from api.errors import validation_error
            err = validation_error(message="Invalid request parameters")
            return JSONResponse(
                content=err.to_response(),
                status_code=400,
            )
        except PermissionError as exc:
            logger.warning("PermissionError: %s", exc)
            from api.errors import auth_error
            err = auth_error(message=str(exc), code=ErrorCode.AUTH_FORBIDDEN)
            return JSONResponse(
                content=err.to_response(),
                status_code=403,
            )
        except FileNotFoundError as exc:
            logger.warning("FileNotFoundError: %s", exc)
            from api.errors import not_found_error
            err = not_found_error(message="Resource not found")
            return JSONResponse(
                content=err.to_response(),
                status_code=404,
            )
        except TimeoutError as exc:
            logger.error("TimeoutError: %s", exc)
            from api.errors import market_data_error
            err = market_data_error(message=str(exc), code=ErrorCode.MARKET_DATA_TIMEOUT)
            return JSONResponse(
                content=err.to_response(),
                status_code=504,
            )
        except Exception as exc:
            error_id = uuid.uuid4().hex[:12]
            tb = traceback.format_exc()
            logger.error(
                "Unhandled exception [%s]: %s\n%s",
                error_id, exc, tb,
            )
            err = AppError(
                error_code=ErrorCode.SYSTEM_INTERNAL,
                message=f"Internal server error (ref: {error_id})",
            )
            return JSONResponse(
                content=err.to_response(),
                status_code=500,
            )
