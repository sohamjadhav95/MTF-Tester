"""
Strategy Template — Single Source of Truth
==========================================
All user strategies subclass BaseStrategy and define a StrategyConfig.

NEW ARCHITECTURE:
- Engine always provides M1 (1-minute) bar data.
- Strategy receives M1 DataFrame and handles ALL computation internally.
- If your strategy needs H4 data: resample M1 to H4 in on_start().
- Timeframes are just config fields (Literal dropdowns) — no special handling.
- on_start() pre-computes ALL indicators into self._cache (index-aligned to M1).
- on_bar() reads ONLY from self._cache — never recomputes indicators.

DESIGN RULE:
  on_start() = expensive computation  (called once, or on cache refresh)
  on_bar()   = O(1) cache read + signal logic  (called on every M1 bar)
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

    Subclass this with typed Field() definitions.
    Pydantic auto-generates the JSON Schema that renders as UI inputs.

    Field types → UI widgets:
      int / float             → number input
      Literal["a", "b", "c"] → dropdown select
    """
    model_config = {"extra": "forbid"}


# ─── Base Strategy ──────────────────────────────────────────────
class BaseStrategy(ABC):
    """
    Abstract base for all trading strategies.

    To create a strategy:
      1. Subclass StrategyConfig with your typed fields (including TF dropdowns)
      2. Subclass BaseStrategy, set name / description / config_model
      3. Implement on_start() — pre-compute ALL indicators into self._cache
      4. Implement on_bar() — read from cache, return signal
      5. Optionally implement get_indicator_data() for chart overlay

    The system auto-discovers your file, validates it, and renders the UI.
    """

    name:         ClassVar[str] = ""
    description:  ClassVar[str] = ""
    config_model: ClassVar[Type[StrategyConfig]] = StrategyConfig

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        if settings:
            self.config: StrategyConfig = self.config_model.model_validate(settings)
        else:
            self.config = self.config_model()
        self._cache: dict = {}

    @classmethod
    def get_json_schema(cls) -> dict:
        """Return JSON Schema for this strategy's config (used by frontend)."""
        return cls.config_model.model_json_schema()

    def on_start(self, data: pd.DataFrame) -> None:
        """
        Called ONCE before bar loop begins, and on each cache refresh (live).

        data: Full M1 DataFrame (up to 3000 bars).
              Columns: time, open, high, low, close, volume, spread

        Pre-compute ALL indicators here. Store everything in self._cache.
        Index positions in cache arrays MUST align with M1 bar indices.

        If you need H4 data:
            h4 = self._resample(data, '4H')
            # compute H4 indicators
            # map H4 signal back to M1 index (see _resample helper below)

        IMPORTANT: Do NOT reset self._cache here in a way that loses live state.
        Override carefully if you maintain persistent state across bar loops.
        """
        pass

    def on_finish(self, data: pd.DataFrame) -> None:
        """Called once after bar loop ends. Override if needed."""
        pass

    @abstractmethod
    def on_bar(self, index: int, data: pd.DataFrame) -> str | tuple:
        """
        Called on every M1 bar. Must be fast — reads from self._cache only.

        Args:
            index: Current bar index in data (0-based).
            data:  Full M1 DataFrame up to and including current bar.
                   DO NOT compute indicators here. Read from self._cache.

        Returns:
            "BUY"  | "SELL" | "HOLD"
            ("BUY",  sl_price, tp_price)
            ("SELL", sl_price, tp_price)
            SL/TP values are absolute prices, not pip distances.
            Use None for missing SL or TP: ("BUY", None, 1.0950)
        """
        ...

    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        """
        Return indicator values for chart overlay. Called after backtest.

        Returns dict where:
          key   = indicator label (shown in legend)
          value = list of float or None, SAME LENGTH as data (M1 bars)

        Naming hint:
          Contains "rsi", "macd", "stoch", "oscillator", "histogram"
            → renders in separate pane below chart
          Everything else → overlaid on price chart
        """
        return {}

    # ─── Helpers available to all strategies ────────────────────

    @staticmethod
    def _resample(m1_data: pd.DataFrame, rule: str) -> pd.DataFrame:
        """
        Resample M1 DataFrame to a coarser timeframe.

        Args:
            m1_data: M1 DataFrame with 'time' column as pd.Timestamp
            rule:    Pandas offset alias — '5min', '15min', '1h', '4h', '1D'
                     Common mappings:
                       M5  → '5min'    M15 → '15min'   M30 → '30min'
                       H1  → '1h'      H4  → '4h'      D1  → '1D'

        Returns:
            Resampled OHLCV DataFrame, indexed by bar open time.
            Columns: time, open, high, low, close, volume
            Only completed bars included (no partial bar at end).

        Usage in on_start():
            h4 = self._resample(data, '4h')
            h4_close = h4['close'].values.astype(float)
        """
        df = m1_data.copy()
        df = df.set_index('time')
        resampled = df.resample(rule, closed='left', label='left').agg({
            'open':   'first',
            'high':   'max',
            'low':    'min',
            'close':  'last',
            'volume': 'sum',
        }).dropna(subset=['open'])
        resampled = resampled.reset_index()
        resampled = resampled.rename(columns={'time': 'time'})
        # Drop last bar (may be incomplete/partial).
        # For M1→M1 (rule='1min'), the last bar is already complete — don't drop it.
        if rule != "1min" and len(resampled) > 1:
            resampled = resampled.iloc[:-1]
        return resampled.reset_index(drop=True)

    @staticmethod
    def _m1_to_htf_index(m1_times: pd.Series, htf_times: pd.Series) -> list[int]:
        """
        For each M1 bar, find the index of its corresponding HTF bar.
        Returns list of length len(m1_times). Value is -1 if no HTF bar found.

        Usage in on_start():
            h4 = self._resample(data, '4h')
            m1_to_h4 = self._m1_to_htf_index(data['time'], h4['time'])
            # At on_bar index i: h4_idx = m1_to_h4[i]

        This enables O(1) HTF lookups in on_bar().
        """
        htf_arr = htf_times.values
        mapping = []
        h_idx = -1
        for m_time in m1_times:
            # Advance HTF pointer while next HTF bar has started
            while (h_idx + 1 < len(htf_arr)) and (htf_arr[h_idx + 1] <= m_time):
                h_idx += 1
            mapping.append(h_idx)
        return mapping
