"""
Strategy Template — Single Source of Truth
==========================================
All user-authored strategies must subclass `BaseStrategy` and define
a `StrategyConfig` Pydantic model for typed configuration.

The Pydantic model IS the schema: JSON Schema is auto-generated
via `config_model.model_json_schema()` and served to the frontend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Type

import pandas as pd
from pydantic import BaseModel


# ─── Base Config ────────────────────────────────────────────────
class StrategyConfig(BaseModel):
    """
    Base configuration for all strategies.

    Subclass this with typed `Field()` definitions.
    The resulting Pydantic model becomes the single source of truth
    for validation, defaults, and JSON Schema generation.
    """

    model_config = {"extra": "forbid"}


# ─── Base Strategy ──────────────────────────────────────────────
class BaseStrategy(ABC):
    """
    Abstract base class for every trading strategy.

    To create a strategy:
      1. Subclass `StrategyConfig` with typed fields
      2. Subclass `BaseStrategy`, set `name`, `description`, `config_model`
      3. Implement `on_bar()`
      4. Drop the file into `backend/strategies/`

    Done — the system discovers, validates, and serves it automatically.
    """

    # ── Class-level metadata (override in subclass) ─────────────
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    config_model: ClassVar[Type[StrategyConfig]] = StrategyConfig

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        """
        Instantiate with optional raw settings dict.
        Settings are validated & coerced through the Pydantic model.
        Missing keys fall back to model defaults.
        """
        if settings:
            self.config: StrategyConfig = self.config_model.model_validate(settings)
        else:
            self.config = self.config_model()

    # ── Schema helper ───────────────────────────────────────────
    @classmethod
    def get_json_schema(cls) -> dict:
        """Return the full JSON Schema for this strategy's config."""
        return cls.config_model.model_json_schema()

    # ── Lifecycle hooks ─────────────────────────────────────────
    def on_start(self, data: pd.DataFrame) -> None:
        """Called once before the bar loop begins. Override if needed."""
        pass

    def on_finish(self, data: pd.DataFrame) -> None:
        """Called once after the bar loop ends. Override if needed."""
        pass

    # ── Core contract ───────────────────────────────────────────
    @abstractmethod
    def on_bar(self, index: int, data: pd.DataFrame) -> str | tuple:
        """
        Called on each bar during backtesting.

        Args:
            index: Current bar index (0-based).
            data:  DataFrame with all bars up to and including current bar.
                   Columns: time, open, high, low, close, volume, spread.
                   IMPORTANT: data contains ONLY bars up to current index.
                   There is NO look-ahead — you cannot access future bars.

        Returns:
            Signal string: "BUY", "SELL", or "HOLD"
            — OR —
            Tuple: ("BUY", sl_price, tp_price) / ("SELL", sl_price, tp_price)
        """
        ...

    # ── Optional indicator overlay ──────────────────────────────
    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        """
        Return indicator values for chart overlay.

        Called AFTER the backtest completes with the full dataset.
        Return a dict where keys are indicator names and values are
        lists of floats (same length as data, use None for NaN).
        """
        return {}
