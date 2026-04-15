"""
Strategy Auto-Discovery
========================
Scans the strategies/ directory and imports all valid BaseStrategy subclasses.
Called once at startup and cached.
"""

import importlib
import sys
from pathlib import Path
from main.logger import get_logger
from main.config import STRATEGIES_DIR

log = get_logger("engine")
_registry: dict = {}


def auto_discover_strategies() -> dict:
    global _registry
    if _registry:
        return _registry

    strategy_dir = STRATEGIES_DIR
    if not strategy_dir.exists():
        log.warning(f"Strategies directory not found: {strategy_dir}")
        return {}

    from strategies._template import BaseStrategy

    for path in strategy_dir.glob("*.py"):
        if path.stem.startswith("_"):
            continue
        module_name = f"strategies.{path.stem}"
        try:
            # Use importlib.import_module for proper package-relative imports
            module = importlib.import_module(module_name)
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if (isinstance(obj, type)
                        and issubclass(obj, BaseStrategy)
                        and obj is not BaseStrategy
                        and hasattr(obj, "name")
                        and obj.name):
                    _registry[obj.name] = obj
                    log.info(f"Loaded strategy: {obj.name}")
        except Exception as e:
            log.error(f"Failed to load strategy from {path.name}: {e}")

    return _registry
