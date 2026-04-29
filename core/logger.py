import json
import logging
import logging.handlers
import time
from collections import deque
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOG_DIR = DATA_DIR / "logs"
ERROR_LOG_PATH = LOG_DIR / "error.log"
APP_LOG_PATH = LOG_DIR / "app.log"

_LOGGER_INITIALIZED = False


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S.%f", time.localtime(record.created)),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
            "filename": record.filename,
            "lineno": record.lineno,
        }
        if hasattr(record, "extra"):
            log_record.update(record.extra)
        if record.exc_info:
            import traceback
            log_record["exception"] = traceback.format_exc()
        return json.dumps(log_record, ensure_ascii=False)


def setup_logger(level: int = logging.INFO) -> None:
    global _LOGGER_INITIALIZED
    if _LOGGER_INITIALIZED:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    app_handler = logging.handlers.RotatingFileHandler(
        APP_LOG_PATH,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(JSONFormatter())

    error_handler = logging.handlers.RotatingFileHandler(
        ERROR_LOG_PATH,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(JSONFormatter())

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    console_handler.setFormatter(console_formatter)

    root_logger.addHandler(app_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)

    for noisy in [
        "numexpr", "numexpr.utils", "numpy", "urllib3", "urllib3.connectionpool",
        "httpx", "httpcore", "asyncio", "multipart", "py.warnings",
        "PIL", "matplotlib", "akshare", "baostock",
    ]:
        logging.getLogger(noisy).setLevel(logging.ERROR)

    _LOGGER_INITIALIZED = True


def get_recent_logs(limit: int = 100, level: Optional[str] = None) -> list[dict]:
    if not APP_LOG_PATH.exists():
        return []

    rows: deque[dict] = deque(maxlen=limit)
    try:
        with open(APP_LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
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
    """获取带有上下文支持的日志记录器"""
    return logging.getLogger(name)


# 默认日志记录器实例
logger = logging.getLogger("quantcore")


def log_with_context(logger: logging.Logger, level: int, message: str, **kwargs) -> None:
    """带有上下文信息的日志记录"""
    extra = kwargs
    logger.log(level, message, extra={"extra": extra})


def log_error(logger: logging.Logger, message: str, error: Exception = None, **kwargs) -> None:
    """记录错误日志"""
    extra = kwargs
    if error:
        extra["error_type"] = type(error).__name__
        extra["error_message"] = str(error)
    logger.error(message, extra={"extra": extra})


def log_warning(logger: logging.Logger, message: str, **kwargs) -> None:
    """记录警告日志"""
    extra = kwargs
    logger.warning(message, extra={"extra": extra})


def log_info(logger: logging.Logger, message: str, **kwargs) -> None:
    """记录信息日志"""
    extra = kwargs
    logger.info(message, extra={"extra": extra})


def log_debug(logger: logging.Logger, message: str, **kwargs) -> None:
    """记录调试日志"""
    extra = kwargs
    logger.debug(message, extra={"extra": extra})
