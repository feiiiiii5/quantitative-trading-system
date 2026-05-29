import hashlib
import importlib
import importlib.util
import logging
import sys
import time
import types
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class StrategyHotReloader:
    def __init__(self, watch_dir: Path | None = None) -> None:
        self._watch_dir = watch_dir or Path.home() / ".quantcore" / "strategies"
        self._watch_dir.mkdir(parents=True, exist_ok=True)
        self._loaded_strategies: dict[str, tuple[types.ModuleType, float]] = {}
        self._code_hashes: dict[str, str] = {}

    def _compute_hash(self, code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def load_strategy(self, strategy_id: str, code: str) -> types.ModuleType:
        code_hash = self._compute_hash(code)
        module_name = f"quantcore_strategy_user.{strategy_id}"

        if strategy_id in self._loaded_strategies and module_name in sys.modules:
            del sys.modules[module_name]

        spec = importlib.util.spec_from_loader(module_name, loader=None)
        if spec is None:
            raise ValueError(f"Failed to create module spec for strategy '{strategy_id}'")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            exec(code, module.__dict__)
        except Exception as e:
            sys.modules.pop(module_name, None)
            logger.error("Failed to load strategy '%s': %s", strategy_id, e)
            raise

        self._loaded_strategies[strategy_id] = (module, time.time())
        self._code_hashes[strategy_id] = code_hash

        strategy_path = self._watch_dir / f"{strategy_id}.py"
        strategy_path.write_text(code, encoding="utf-8")

        logger.info(
            "Loaded strategy '%s' (hash=%s...)",
            strategy_id,
            code_hash[:8],
        )
        return module

    def reload_if_changed(self, strategy_id: str) -> bool:
        if strategy_id not in self._loaded_strategies:
            logger.warning("Strategy '%s' not loaded, cannot reload", strategy_id)
            return False

        strategy_path = self._watch_dir / f"{strategy_id}.py"
        if not strategy_path.exists():
            logger.debug("Strategy file for '%s' not found at %s", strategy_id, strategy_path)
            return False

        current_code = strategy_path.read_text(encoding="utf-8")
        current_hash = self._compute_hash(current_code)

        if current_hash == self._code_hashes.get(strategy_id):
            return False

        logger.info("Detected change in strategy '%s', reloading", strategy_id)
        try:
            self.load_strategy(strategy_id, current_code)
            return True
        except Exception as e:
            logger.error("Failed to reload strategy '%s': %s", strategy_id, e)
            return False

    def get_strategy(self, strategy_id: str) -> Optional[types.ModuleType]:
        if strategy_id not in self._loaded_strategies:
            return None
        module, _ = self._loaded_strategies[strategy_id]
        return module

    def unload_strategy(self, strategy_id: str) -> bool:
        if strategy_id not in self._loaded_strategies:
            return False

        module_name = f"quantcore_strategy_user.{strategy_id}"
        sys.modules.pop(module_name, None)
        del self._loaded_strategies[strategy_id]
        self._code_hashes.pop(strategy_id, None)

        logger.info("Unloaded strategy '%s'", strategy_id)
        return True

    @property
    def loaded_strategy_ids(self) -> list[str]:
        return list(self._loaded_strategies.keys())
