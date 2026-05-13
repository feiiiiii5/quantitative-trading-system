import contextlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    'CONFIG_SCHEMA',
    'DEFAULT_CONFIG',
    'validate_config',
    'load_config',
    'get_config',
    'reload_config',
    'ConfigType',
]

CONFIG_SCHEMA: dict[str, dict[str, Any]] = {
    "server": {
        "type": "object",
        "required": False,
        "properties": {
            "host": {"type": "string", "default": "0.0.0.0"},
            "port": {"type": "integer", "minimum": 1024, "maximum": 65535, "default": 8080},
            "workers": {"type": "integer", "minimum": 1, "maximum": 16, "default": 1},
            "log_level": {"type": "string", "enum": ["debug", "info", "warning", "error"], "default": "info"},
            "cors_origins": {"type": "array", "items": {"type": "string"}, "default": []},
        },
    },
    "backtest": {
        "type": "object",
        "required": False,
        "properties": {
            "initial_capital": {"type": "number", "minimum": 10000, "default": 1000000},
            "commission": {"type": "number", "minimum": 0, "maximum": 0.01, "default": 0.0003},
            "stamp_tax": {"type": "number", "minimum": 0, "maximum": 0.01, "default": 0.001},
            "slippage_pct": {"type": "number", "minimum": 0, "maximum": 0.01, "default": 0.001},
            "use_vectorized": {"type": "boolean", "default": True},
        },
    },
    "risk": {
        "type": "object",
        "required": False,
        "properties": {
            "max_concentration": {"type": "number", "minimum": 0.05, "maximum": 1.0, "default": 0.3},
            "max_daily_loss": {"type": "number", "minimum": 0.01, "maximum": 0.2, "default": 0.05},
            "max_open_trades": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            "trailing_stop": {"type": "number", "minimum": -0.2, "maximum": 0, "default": -0.05},
            "trailing_stop_positive": {"type": "number", "minimum": 0, "maximum": 0.1, "default": 0.02},
            "trailing_stop_positive_offset": {"type": "number", "minimum": 0, "maximum": 0.2, "default": 0.05},
        },
    },
    "api": {
        "type": "object",
        "required": False,
        "properties": {
            "auth_enabled": {"type": "boolean", "default": False},
            "api_key": {"type": "string", "default": ""},
            "rate_limit_per_minute": {"type": "integer", "minimum": 10, "maximum": 10000, "default": 120},
        },
    },
    "strategy": {
        "type": "object",
        "required": False,
        "properties": {
            "buy_threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.30},
            "strong_buy_threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.50},
            "sell_threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.25},
            "cooldown_bars": {"type": "integer", "minimum": 0, "maximum": 20, "default": 3},
            "kelly_cap": {"type": "number", "minimum": 0.1, "maximum": 1.0, "default": 0.65},
            "min_bars_required": {"type": "integer", "minimum": 5, "maximum": 100, "default": 10},
        },
    },
    "data": {
        "type": "object",
        "required": False,
        "properties": {
            "cache_ttl_realtime": {"type": "integer", "minimum": 1, "maximum": 60, "default": 8},
            "cache_ttl_history": {"type": "integer", "minimum": 10, "maximum": 600, "default": 120},
            "max_concurrent_requests": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            "network_timeout_seconds": {"type": "integer", "minimum": 5, "maximum": 120, "default": 30},
            "inflight_max": {"type": "integer", "minimum": 50, "maximum": 2000, "default": 500},
            "inflight_cleanup_interval": {"type": "integer", "minimum": 10, "maximum": 300, "default": 60},
            "buffer_max_size": {"type": "integer", "minimum": 10, "maximum": 1000, "default": 100},
        },
    },
}

DEFAULT_CONFIG: dict[str, dict[str, Any]] = {}

for section, schema in CONFIG_SCHEMA.items():
    DEFAULT_CONFIG[section] = {}
    for key, prop in schema.get("properties", {}).items():
        if "default" in prop:
            DEFAULT_CONFIG[section][key] = prop["default"]


def validate_config(config: dict[str, Any]) -> list[str]:
    errors = []
    for section, schema in CONFIG_SCHEMA.items():
        if section not in config:
            continue
        section_config = config[section]
        if not isinstance(section_config, dict):
            errors.append(f"配置节 '{section}' 必须是对象")
            continue
        for key, prop in schema.get("properties", {}).items():
            if key not in section_config:
                continue
            value = section_config[key]
            expected_type = prop.get("type")
            if expected_type == "string" and not isinstance(value, str):
                errors.append(f"{section}.{key}: 期望字符串，得到 {type(value).__name__}")
            elif expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                errors.append(f"{section}.{key}: 期望整数，得到 {type(value).__name__}")
            elif expected_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
                errors.append(f"{section}.{key}: 期望数字，得到 {type(value).__name__}")
            elif expected_type == "boolean" and not isinstance(value, bool):
                errors.append(f"{section}.{key}: 期望布尔值，得到 {type(value).__name__}")

            if "enum" in prop and value not in prop["enum"]:
                errors.append(f"{section}.{key}: 值 '{value}' 不在允许范围 {prop['enum']} 中")
            if "minimum" in prop and isinstance(value, (int, float)) and value < prop["minimum"]:
                errors.append(f"{section}.{key}: 值 {value} 小于最小值 {prop['minimum']}")
            if "maximum" in prop and isinstance(value, (int, float)) and value > prop["maximum"]:
                errors.append(f"{section}.{key}: 值 {value} 大于最大值 {prop['maximum']}")
    return errors


def load_config(config_path: str | None = None) -> dict[str, Any]:
    config: dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))

    if config_path and Path(config_path).exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                user_config = json.load(f)
            _deep_merge(config, user_config)
            logger.info("配置已从 %s 加载", config_path)
        except Exception as e:
            logger.warning("加载配置文件失败: %s", e)

    for section in config:
        env_prefix = f"QUANTCORE_{section.upper()}_"
        for key in list(os.environ.keys()):
            if key.startswith(env_prefix):
                config_key = key[len(env_prefix):].lower()
                val = os.environ[key]
                if config_key in config.get(section, {}):
                    current = config[section].get(config_key)
                    if isinstance(current, bool):
                        config[section][config_key] = val.lower() in ("true", "1", "yes")
                    elif isinstance(current, int):
                        with contextlib.suppress(ValueError):
                            config[section][config_key] = int(val)
                    elif isinstance(current, float):
                        with contextlib.suppress(ValueError):
                            config[section][config_key] = float(val)
                    else:
                        config[section][config_key] = val

    errors = validate_config(config)
    if errors:
        for err in errors:
            logger.warning("配置验证警告: %s", err)

    return config


def _deep_merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


ConfigType = dict[str, Any]

_config_instance: ConfigType | None = None
_config_lock = threading.Lock()


def get_config() -> ConfigType:
    global _config_instance
    if _config_instance is None:
        with _config_lock:
            if _config_instance is None:
                config_path = os.environ.get("QUANTCORE_CONFIG", str(Path(__file__).parent.parent / "config.json"))
                _config_instance = load_config(config_path)
    return _config_instance


def reload_config() -> dict[str, Any]:
    global _config_instance
    with _config_lock:
        _config_instance = None
    return get_config()
