"""
Strategy Registry — Zero Manual Registration
=============================================
Auto-discovers strategy files in the `strategies/` directory,
imports them dynamically, and registers all valid BaseStrategy subclasses.

Usage:
    from app.core.registry import auto_discover_strategies

    registry = auto_discover_strategies()        # dict[str, Type[BaseStrategy]]
    strategy_cls = registry["EMA Crossover"]
    instance = strategy_cls(settings={...})
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Type

from app.core.strategy_template import BaseStrategy

# ─── Global Registry ────────────────────────────────────────────
STRATEGY_REGISTRY: dict[str, Type[BaseStrategy]] = {}


def auto_discover_strategies(
    strategies_dir: Path | str | None = None,
) -> dict[str, Type[BaseStrategy]]:
    """
    Scan `strategies_dir` for .py files containing BaseStrategy subclasses.

    Args:
        strategies_dir: Path to scan.  Defaults to `backend/strategies/`.

    Returns:
        Dict mapping strategy display name → strategy class.
    """
    global STRATEGY_REGISTRY

    if strategies_dir is None:
        # Default: <backend>/strategies/
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies"
    else:
        strategies_dir = Path(strategies_dir)

    if not strategies_dir.is_dir():
        print(f"[registry] Warning: strategies directory not found: {strategies_dir}")
        return STRATEGY_REGISTRY

    discovered: dict[str, Type[BaseStrategy]] = {}

    for filepath in sorted(strategies_dir.glob("*.py")):
        if filepath.name.startswith("_"):
            continue  # skip __init__.py, __pycache__, etc.

        module_name = f"strategies.{filepath.stem}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                continue

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module      # allow relative refs
            spec.loader.exec_module(module)

            # Find all concrete BaseStrategy subclasses in the module
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    inspect.isclass(attr)
                    and issubclass(attr, BaseStrategy)
                    and attr is not BaseStrategy
                    and not inspect.isabstract(attr)
                ):
                    if not attr.name:
                        print(
                            f"[registry] Skipping {attr_name} in {filepath.name}: "
                            f"missing 'name' class attribute"
                        )
                        continue

                    discovered[attr.name] = attr

        except Exception as e:
            print(f"[registry] Warning: failed to load {filepath.name}: {e}")

    STRATEGY_REGISTRY = discovered
    return STRATEGY_REGISTRY
