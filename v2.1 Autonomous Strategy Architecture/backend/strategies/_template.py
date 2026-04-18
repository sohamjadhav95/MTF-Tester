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


TF_DURATION = {
    "M1":  pd.Timedelta(minutes=1),
    "M5":  pd.Timedelta(minutes=5),
    "M15": pd.Timedelta(minutes=15),
    "M30": pd.Timedelta(minutes=30),
    "H1":  pd.Timedelta(hours=1),
    "H4":  pd.Timedelta(hours=4),
    "D1":  pd.Timedelta(days=1),
    "W1":  pd.Timedelta(weeks=1),
}


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
        Called ONCE before the bar loop, and ALSO on each live poll when new bars
        arrive. Live calls receive the updated rolling M1 DataFrame (last 3000 bars).
        Keep this method fast — it runs on every M1 update (~once/minute in live mode).

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

        REQUIRED cache entries (if your strategy uses HTF):
            self._cache["m1_to_htf"]  : list[int] — from _m1_to_completed_htf_index
            self._cache["htf_times"]  : array — htf bar open times (np.datetime64 or pd.Timestamp)

        These enable the live scanner to dedup signals by HTF-bar open-time rather
        than by index (which is unstable across rolling-window trims).
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
    def _m1_to_completed_htf_index(
        m1_times: pd.Series,
        htf_times: pd.Series,
        htf_duration: pd.Timedelta,
    ) -> list[int]:
        """
        For each M1 bar, return the index of the last HTF bar that has FULLY CLOSED
        by the end of that M1 bar. Returns -1 if no HTF bar has closed yet.

        An HTF bar labeled T covers [T, T + htf_duration). It closes at T + htf_duration.
        An M1 bar labeled t covers [t, t + 1min). It closes at t + 1min.
        HTF[k] is available to the strategy at M1[i]'s close iff
            htf_open[k] + htf_duration  <=  m1_open[i] + 1min.

        The boundary case: at M1 labeled htf_open[k+1] (the first M1 of HTF[k+1]'s
        window), HTF[k] has just completed. That's where signals fire.

        USE THIS in every new strategy. The old `_m1_to_htf_index` is look-ahead-unsafe.
        """
        one_min = pd.Timedelta(minutes=1)
        htf_close_times = [pd.Timestamp(t) + htf_duration for t in htf_times]
        mapping: list[int] = []
        h_idx = -1
        for m_time in m1_times:
            m_close = pd.Timestamp(m_time) + one_min
            while (h_idx + 1 < len(htf_close_times)) and (htf_close_times[h_idx + 1] <= m_close):
                h_idx += 1
            mapping.append(h_idx)
        return mapping

    @staticmethod
    def _m1_to_htf_index(m1_times: pd.Series, htf_times: pd.Series) -> list[int]:
        """
        DEPRECATED: This older mapping is look-ahead unsafe.
        Use `_m1_to_completed_htf_index` instead.

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
