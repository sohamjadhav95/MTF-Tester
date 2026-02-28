"""
Strategy Loader
Auto-discovers strategy .py files in the strategies/ directory.
"""

import os
import importlib
import importlib.util
import inspect
from .base import BaseStrategy


# Files to skip when scanning for strategies
SKIP_FILES = {"__init__.py", "base.py", "loader.py"}


def discover_strategies() -> dict[str, type]:
    """
    Scan the strategies directory for .py files containing BaseStrategy subclasses.
    
    Returns:
        Dict mapping strategy name -> strategy class
    """
    strategies = {}
    strategies_dir = os.path.dirname(os.path.abspath(__file__))

    for filename in os.listdir(strategies_dir):
        if filename in SKIP_FILES:
            continue
        if not filename.endswith(".py"):
            continue

        filepath = os.path.join(strategies_dir, filename)
        module_name = filename[:-3]  # Remove .py

        try:
            # Load the module
            spec = importlib.util.spec_from_file_location(
                f"strategies.{module_name}", filepath
            )
            if spec is None or spec.loader is None:
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find all BaseStrategy subclasses in the module
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    inspect.isclass(attr)
                    and issubclass(attr, BaseStrategy)
                    and attr is not BaseStrategy
                ):
                    # Instantiate with defaults to get the name
                    try:
                        instance = attr()
                        strategies[instance.name] = attr
                    except Exception:
                        # If we can't instantiate with defaults, use class name
                        strategies[attr_name] = attr

        except Exception as e:
            print(f"Warning: Failed to load strategy from {filename}: {e}")

    return strategies


def get_strategy_list(strategies: dict[str, type]) -> list[dict]:
    """
    Get a list of strategy info dicts for the API.
    
    Returns:
        List of {name, description, settings_schema}
    """
    result = []
    for name, cls in strategies.items():
        try:
            instance = cls()
            result.append({
                "name": instance.name,
                "description": instance.description,
                "settings": instance.settings_schema,
            })
        except Exception as e:
            result.append({
                "name": name,
                "description": f"Error loading: {e}",
                "settings": {},
            })
    return result
