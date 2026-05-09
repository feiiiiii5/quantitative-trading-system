__all__ = [
    "setup_logger",
    "get_logger",
    "get_recent_logs",
    "log_with_context",
    "log_error",
    "log_warning",
    "log_info",
    "log_debug",
    "logger",
    "LOG_DIR",
    "APP_LOG_PATH",
    "ERROR_LOG_PATH",
]

import json
import logging
import logging.handlers
import sys
from collections import deque
from pathlib import Path
from typing import Any

from loguru import logger as _loguru_logger

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOG_DIR = DATA_DIR / "logs"
ERROR_LOG_PATH = LOG_DIR / "error.log"
APP_LOG_PATH = LOG_DIR / "app.log"

_LOGGER_INITIALIZED = False

_loguru_format = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level:<8} | "
    "{name}:{function}:{line} | "
    "{message}"
)

_json_format = (
    '{"timestamp":"{time:YYYY-MM-DD HH:mm:ss.SSS}",'
    '"level":"{level}",'
    '"module":"{name}",'
    '"message":"{message}",'
    '"filename":"{file}",'
    '"lineno":"{line}"}'
)


class _LoguruToLoggingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = _loguru_logger.level(record.levelname).no
        except ValueError:
            level = record.levelno

        frame = record
        depth = 0
        while frame and frame.filename != record.filename:
            depth += 1

        _loguru_logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logger(level: int = logging.INFO) -> None:
    global _LOGGER_INITIALIZED
    if _LOGGER_INITIALIZED:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    _loguru_logger.remove()

    _loguru_logger.add(
        sys.stderr,
        format=_loguru_format,
        level=logging.getLevelName(level),
        colorize=True,
    )

    _loguru_logger.add(
        str(APP_LOG_PATH),
        format=_json_format,
        level="INFO",
        rotation="10 MB",
        retention=5,
        compression="gz",
        encoding="utf-8",
        serialize=False,
    )

    _loguru_logger.add(
        str(ERROR_LOG_PATH),
        format=_json_format,
        level="ERROR",
        rotation="5 MB",
        retention=3,
        compression="gz",
        encoding="utf-8",
        serialize=False,
    )

    for noisy in [
        "numexpr", "numexpr.utils", "numpy", "urllib3", "urllib3.connectionpool",
        "httpx", "httpcore", "asyncio", "multipart", "py.warnings",
        "PIL", "matplotlib", "akshare", "baostock",
    ]:
        logging.getLogger(noisy).setLevel(logging.ERROR)

    _LOGGER_INITIALIZED = True


def get_recent_logs(limit: int = 100, level: str | None = None) -> list[dict]:
    if not APP_LOG_PATH.exists():
        return []

    rows: deque[dict] = deque(maxlen=limit)
    try:
        with open(APP_LOG_PATH, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    log_entry = json.loads(line)
                    if level and log_entry.get("level", "").upper() != level.upper():
                        continue
                    rows.append(log_entry)
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass
    return list(rows)[-limit:]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


logger = _loguru_logger.bind(component="quantcore")


def log_with_context(log_instance: Any, level: int, message: str, **kwargs) -> None:
    bound = log_instance.bind(**kwargs)
    bound.log(level, message)


def log_error(log_instance: Any, message: str, error: Exception | None = None, **kwargs) -> None:
    if error:
        kwargs["error_type"] = type(error).__name__
        kwargs["error_message"] = str(error)
    log_instance.bind(**kwargs).error(message)


def log_warning(log_instance: Any, message: str, **kwargs) -> None:
    log_instance.bind(**kwargs).warning(message)


def log_info(log_instance: Any, message: str, **kwargs) -> None:
    log_instance.bind(**kwargs).info(message)


def log_debug(log_instance: Any, message: str, **kwargs) -> None:
    log_instance.bind(**kwargs).debug(message)
