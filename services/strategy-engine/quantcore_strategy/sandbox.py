import ast
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import numpy
import pandas

logger = logging.getLogger(__name__)

_BLOCKED_IMPORTS: frozenset[str] = frozenset({
    "os", "sys", "subprocess", "socket", "http",
    "urllib", "requests", "shutil", "pathlib",
    "importlib", "ctypes", "signal", "multiprocessing",
    "threading", "pickle", "shelve", "marshal",
})

_BLOCKED_BUILTINS: frozenset[str] = frozenset({
    "eval", "exec", "compile", "__import__",
    "open", "input", "breakpoint", "globals",
    "locals", "vars", "dir", "getattr",
    "setattr", "delattr", "type",
})

_ALLOWED_IMPORTS: frozenset[str] = frozenset({
    "pandas", "numpy", "math", "datetime",
})


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class StrategySandbox:
    def __init__(self, default_timeout: float = 30.0) -> None:
        self._default_timeout = default_timeout
        self._safe_globals = self._build_safe_globals()

    def _build_safe_globals(self) -> dict[str, Any]:
        import math
        import datetime

        safe_builtins = {}
        if isinstance(__builtins__, dict):
            safe_builtins = {
                k: v for k, v in __builtins__.items()
                if k not in _BLOCKED_BUILTINS
            }
        else:
            import builtins as _builtins_mod
            safe_builtins = {
                k: getattr(_builtins_mod, k)
                for k in dir(_builtins_mod)
                if k not in _BLOCKED_BUILTINS and not k.startswith("_")
            }

        safe_builtins["__import__"] = self._restricted_import

        return {
            "__builtins__": safe_builtins,
            "pandas": pandas,
            "np": numpy,
            "numpy": numpy,
            "math": math,
            "datetime": datetime,
            "pd": pandas,
        }

    @staticmethod
    def _restricted_import(
        name: str,
        globals: dict | None = None,
        locals: dict | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        top_level = name.split(".")[0]
        if top_level in _BLOCKED_IMPORTS:
            raise ImportError(f"Import of '{name}' is not allowed in strategy sandbox")
        if top_level not in _ALLOWED_IMPORTS and level == 0:
            raise ImportError(
                f"Import of '{name}' is not allowed. "
                f"Allowed: {sorted(_ALLOWED_IMPORTS)}"
            )
        return __import__(name, globals, locals, fromlist, level)

    def validate_strategy_code(self, code: str) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"Syntax error at line {e.lineno}: {e.msg}"],
            )

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_level = alias.name.split(".")[0]
                    if top_level in _BLOCKED_IMPORTS:
                        errors.append(
                            f"Blocked import: '{alias.name}' at line {node.lineno}"
                        )
                    elif top_level not in _ALLOWED_IMPORTS:
                        warnings.append(
                            f"Non-standard import: '{alias.name}' at line {node.lineno}"
                        )

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top_level = node.module.split(".")[0]
                    if top_level in _BLOCKED_IMPORTS:
                        errors.append(
                            f"Blocked import from: '{node.module}' at line {node.lineno}"
                        )
                    elif top_level not in _ALLOWED_IMPORTS:
                        warnings.append(
                            f"Non-standard import from: '{node.module}' at line {node.lineno}"
                        )

            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in _BLOCKED_BUILTINS:
                    errors.append(
                        f"Blocked builtin call: '{node.func.id}' at line {node.lineno}"
                    )

            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "__builtins__" and node.attr in _BLOCKED_BUILTINS:
                errors.append(
                        f"Blocked builtin access: __builtins__.{node.attr} "
                        f"at line {node.lineno}"
                    )

        if not errors and not self._has_entry_point(tree):
            warnings.append(
                "Strategy code does not define 'initialize' or 'handle_data' function"
            )

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _has_entry_point(tree: ast.Module) -> bool:
        required = {"initialize", "handle_data"}
        defined: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(node.name)
        return bool(required & defined)

    async def execute_strategy(
        self,
        code: str,
        context: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        timeout = timeout or self._default_timeout
        validation = self.validate_strategy_code(code)
        if not validation.is_valid:
            return {
                "success": False,
                "errors": validation.errors,
                "warnings": validation.warnings,
            }

        local_ns: dict[str, Any] = dict(context)
        start = time.monotonic()

        try:
            result = await asyncio.wait_for(
                self._run_in_executor(code, local_ns),
                timeout=timeout,
            )
            elapsed = time.monotonic() - start
            result["execution_time_s"] = round(elapsed, 4)
            return result
        except asyncio.TimeoutError:
            logger.warning("Strategy execution timed out after %.1fs", timeout)
            return {
                "success": False,
                "errors": [f"Strategy execution timed out after {timeout}s"],
                "execution_time_s": timeout,
            }
        except Exception as e:
            logger.exception("Strategy execution failed")
            return {
                "success": False,
                "errors": [f"{type(e).__name__}: {e}"],
                "execution_time_s": time.monotonic() - start,
            }

    async def _run_in_executor(
        self,
        code: str,
        local_ns: dict[str, Any],
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._exec_sync,
            code,
            local_ns,
        )

    def _exec_sync(self, code: str, local_ns: dict[str, Any]) -> dict[str, Any]:
        exec(code, dict(self._safe_globals), local_ns)

        result: dict[str, Any] = {"success": True, "data": {}}
        for key in ("signals", "positions", "orders", "metrics"):
            if key in local_ns:
                result["data"][key] = local_ns[key]
        if "initialize" in local_ns:
            init_fn = local_ns["initialize"]
            if callable(init_fn):
                init_result = init_fn(local_ns.get("context", {}))
                if init_result is not None:
                    result["data"]["initialize_result"] = init_result
        if "handle_data" in local_ns:
            handle_fn = local_ns["handle_data"]
            if callable(handle_fn):
                handle_result = handle_fn(local_ns.get("data", {}))
                if handle_result is not None:
                    result["data"]["handle_data_result"] = handle_result
        return result
