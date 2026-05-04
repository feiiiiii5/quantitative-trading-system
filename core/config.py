import json
import os
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CONFIG_SCHEMA = {
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
    "data": {
        "type": "object",
        "required": False,
        "properties": {
            "cache_ttl_realtime": {"type": "integer", "minimum": 1, "maximum": 60, "default": 8},
            "cache_ttl_history": {"type": "integer", "minimum": 10, "maximum": 600, "default": 120},
            "max_concurrent_requests": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
        },
    },
}

DEFAULT_CONFIG = {}

for section, schema in CONFIG_SCHEMA.items():
    DEFAULT_CONFIG[section] = {}
    for key, prop in schema.get("properties", {}).items():
        if "default" in prop:
            DEFAULT_CONFIG[section][key] = prop["default"]


def validate_config(config: Dict[str, Any]) -> List[str]:
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
            elif expected_type == "integer" and not isinstance(value, int):
                errors.append(f"{section}.{key}: 期望整数，得到 {type(value).__name__}")
            elif expected_type == "number" and not isinstance(value, (int, float)):
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


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))

    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            _deep_merge(config, user_config)
            logger.info(f"配置已从 {config_path} 加载")
        except Exception as e:
            logger.warning(f"加载配置文件失败: {e}")

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
                        try:
                            config[section][config_key] = int(val)
                        except ValueError:
                            pass
                    elif isinstance(current, float):
                        try:
                            config[section][config_key] = float(val)
                        except ValueError:
                            pass
                    else:
                        config[section][config_key] = val

    errors = validate_config(config)
    if errors:
        for err in errors:
            logger.warning(f"配置验证警告: {err}")

    return config


def _deep_merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


_config_instance: Optional[Dict[str, Any]] = None
_config_lock = threading.Lock()


def get_config() -> Dict[str, Any]:
    global _config_instance
    if _config_instance is None:
        with _config_lock:
            if _config_instance is None:
                config_path = os.environ.get("QUANTCORE_CONFIG", str(Path(__file__).parent.parent / "config.json"))
                _config_instance = load_config(config_path)
    return _config_instance


def reload_config() -> Dict[str, Any]:
    global _config_instance
    with _config_lock:
        _config_instance = None
    return get_config()
