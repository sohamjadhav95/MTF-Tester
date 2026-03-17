"""
Grid Pyramiding Strategy
========================
A trend-following pyramiding system that stacks positions at ATR-based grid
levels as price moves in the trend direction, then exits the entire basket
when price retraces one grid from the cycle's extreme.

How it works
------------
1.  An initial position opens at the trigger bar's close in the chosen direction.
2.  Each time price advances one grid from the LAST entry price, a new position
    is added (pyramiding only in the profit direction — never averaging down).
3.  The extreme price (highest close for LONG, lowest close for SHORT) is
    tracked continuously.
4.  The exit trigger = extreme - grid_size (LONG) or extreme + grid_size (SHORT).
    It is a hard, ratcheting trailing stop.
5.  When close crosses through the exit trigger all positions close at once.
6.  The cycle immediately restarts in the SAME direction (or opposite if
    ``direction_switch_on_loss`` is enabled and the cycle was a loser).

Engine compatibility note
--------------------------
The v1.5 engine handles exactly ONE open position at a time.
This strategy maps its multi-position cycle onto that model:

  - The engine tracks ONE "anchor" position representing the active cycle.
  - Virtual positions (the pyramid) are tracked internally via
    ``_virtual_positions``.
  - The engine's per-trade P&L reflects only the anchor position (L0).
  - The TRUE cycle P&L (all virtual positions) accumulates in
    ``indicator_data["Virtual P&L (cumul.)"]``.

Use the "Virtual P&L (cumul.)" overlay for realistic multi-position results.

Optional enhancements (all configurable)
-----------------------------------------
- ``direction_switch_on_loss`` — flip to the opposite direction after a
  losing cycle.
- ``dynamic_atr_grid`` — recompute grid_size from ATR at each bar instead of
  locking it in at cycle start.
- ``position_size`` — fixed units per virtual position (cosmetic; engine
  always uses 1 lot per engine position).

Author : MTF-Tester project
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field

from app.core.strategy_template import BaseStrategy, StrategyConfig


# ─── Pydantic Config ────────────────────────────────────────────────────────

class GridPyramidingConfig(StrategyConfig):
    """Typed configuration for the Grid Pyramiding strategy."""

    # ── Grid settings ────────────────────────────────────────────
    atr_period: int = Field(
        14, ge=2, le=200,
        description="ATR Period (grid size = ATR × multiplier)",
        json_schema_extra={"step": 1},
    )
    atr_multiplier: float = Field(
        1.0, ge=0.1, le=10.0,
        description="ATR Multiplier  (grid size = ATR × this value)",
        json_schema_extra={"step": 0.1},
    )
    max_positions: int = Field(
        10, ge=1, le=50,
        description="Max virtual positions per cycle",
        json_schema_extra={"step": 1},
    )
    dynamic_atr_grid: bool = Field(
        False,
        description=(
            "Dynamic ATR Grid — recompute grid_size from current ATR each bar "
            "instead of locking it in at cycle start"
        ),
    )

    # ── Trend filter ─────────────────────────────────────────────
    trend_filter: Literal["ema_slope", "none"] = Field(
        "ema_slope",
        description=(
            "Trend filter — ema_slope: price above EMA + EMA sloping upward; "
            "none: always active"
        ),
    )
    ema_period: int = Field(
        50, ge=5, le=500,
        description="EMA Period (used by ema_slope filter)",
        json_schema_extra={"step": 1, "x-visible-when": {"trend_filter": ["ema_slope"]}},
    )

    # ── Trade direction ──────────────────────────────────────────
    trade_direction: Literal["both", "long_only", "short_only"] = Field(
        "both",
        description="Trade Direction",
    )

    # ── Optional enhancements ────────────────────────────────────
    direction_switch_on_loss: bool = Field(
        False,
        description=(
            "Direction Switch On Loss — after a losing cycle, flip to the "
            "opposite direction for the next cycle"
        ),
    )


# ─── Strategy ───────────────────────────────────────────────────────────────

class GridPyramiding(BaseStrategy):
    """
    Grid Pyramiding Strategy.

    Stacks positions at ATR-based grid levels as price trends in one direction.
    Exits the entire basket when price retraces one grid from the cycle extreme.
    Re-enters immediately in the same direction (or opposite after a loss if
    ``direction_switch_on_loss`` is enabled).
    """

    name = "Grid Pyramiding"
    description = (
        "ATR-based trend-following pyramiding. Adds a position at each grid "
        "level as price advances, then closes the entire basket on a one-grid "
        "pullback from the peak. EMA slope optional trend filter."
    )
    config_model = GridPyramidingConfig

    # ─── on_start ────────────────────────────────────────────────

    def on_start(self, data: pd.DataFrame) -> None:
        """Reset all internal state before the bar loop begins."""
        self._reset_state()

    def _reset_state(self) -> None:
        """Full state reset — call on_start and after each backtest reset."""
        # ── Cycle state ─────────────────────────────────────────
        self._cycle_active: bool = False
        self._cycle_dir: str | None = None          # "BUY" | "SELL"

        # Virtual position list — each entry is a dict:
        #   {"price": float}  (entry price of that virtual position)
        self._virtual_positions: list[dict] = []

        # Last grid level entry price (add next position when price crosses
        # last_entry_price ± grid_size)
        self._last_entry_price: float | None = None

        # Extreme price tracking
        self._max_price: float | None = None        # running high for LONG
        self._min_price: float | None = None        # running low for SHORT

        # Locked grid size at cycle open (overridden each bar if dynamic_atr_grid)
        self._cycle_grid_size: float | None = None

        # Derived: one-grid trailing stop
        self._exit_trigger: float | None = None

        # ── Per-bar overlay histories ────────────────────────────
        self._exit_trigger_history: list[float | None] = []
        self._virtual_pnl_history: list[float | None] = []
        self._cumul_virtual_pnl: float = 0.0

        # ── Direction preference for next cycle ──────────────────
        # Starts as None → determined by trend filter on first signal
        self._preferred_dir: str | None = None

    # ─── ATR (Wilder's smoothing — matches MT5 / TradingView) ────

    def _compute_atr(self, data: pd.DataFrame, period: int) -> np.ndarray:
        high  = data["high"].values.astype(float)
        low   = data["low"].values.astype(float)
        close = data["close"].values.astype(float)
        n = len(close)

        tr = np.empty(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )

        atr = np.full(n, np.nan)
        if n >= period:
            atr[period - 1] = np.mean(tr[:period])
            for i in range(period, n):
                atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        return atr

    # ─── EMA (standard exponential — matches MT5 / TradingView) ──

    def _compute_ema(self, series: pd.Series, period: int) -> np.ndarray:
        values = series.values.astype(float)
        ema = np.full(len(values), np.nan)
        k = 2.0 / (period + 1)
        if len(values) < period:
            return ema
        ema[period - 1] = np.mean(values[:period])
        for i in range(period, len(values)):
            ema[i] = values[i] * k + ema[i - 1] * (1 - k)
        return ema

    # ─── Trend detection ─────────────────────────────────────────

    def _trend_up(self, index: int, data: pd.DataFrame, ema: np.ndarray) -> bool:
        """True when price is above EMA and EMA is sloping upward (or filter off)."""
        if self.config.trend_filter == "none":
            return True
        if index < 1 or np.isnan(ema[index]) or np.isnan(ema[index - 1]):
            return False
        close = float(data["close"].iloc[index])
        return close > ema[index] and ema[index] > ema[index - 1]

    def _trend_down(self, index: int, data: pd.DataFrame, ema: np.ndarray) -> bool:
        """True when price is below EMA and EMA is sloping downward (or filter off)."""
        if self.config.trend_filter == "none":
            return True
        if index < 1 or np.isnan(ema[index]) or np.isnan(ema[index - 1]):
            return False
        close = float(data["close"].iloc[index])
        return close < ema[index] and ema[index] < ema[index - 1]

    # ─── Cycle helpers ───────────────────────────────────────────

    def _open_position(self, price: float) -> None:
        """
        Add one virtual position at ``price``.
        Updates ``_last_entry_price`` and immediately recalculates the exit
        trigger from the current extreme.
        """
        self._virtual_positions.append({"price": price})
        self._last_entry_price = price
        self._recalc_exit_trigger()

    def _recalc_exit_trigger(self) -> None:
        """
        Recompute the exit trigger from the current extreme and grid size.

        LONG : exit_trigger = max_price - grid_size
        SHORT: exit_trigger = min_price + grid_size
        """
        gs = self._cycle_grid_size
        if self._cycle_dir == "BUY" and self._max_price is not None:
            self._exit_trigger = self._max_price - gs
        elif self._cycle_dir == "SELL" and self._min_price is not None:
            self._exit_trigger = self._min_price + gs

    def _start_buy_cycle(self, price: float, grid_size: float) -> None:
        """Open a new LONG cycle with the first virtual position at ``price``."""
        self._cycle_active = True
        self._cycle_dir = "BUY"
        self._preferred_dir = "BUY"
        self._cycle_grid_size = grid_size
        self._virtual_positions = []
        self._last_entry_price = None
        self._max_price = price          # initialise extreme to entry price
        self._min_price = None
        # Place the anchor position; this also sets _last_entry_price and
        # _exit_trigger via _open_position → _recalc_exit_trigger
        self._open_position(price)

    def _start_sell_cycle(self, price: float, grid_size: float) -> None:
        """Open a new SHORT cycle with the first virtual position at ``price``."""
        self._cycle_active = True
        self._cycle_dir = "SELL"
        self._preferred_dir = "SELL"
        self._cycle_grid_size = grid_size
        self._virtual_positions = []
        self._last_entry_price = None
        self._max_price = None
        self._min_price = price          # initialise extreme to entry price
        self._open_position(price)

    def _update_buy_cycle(self, high: float, grid_size: float) -> None:
        """
        Update a LONG cycle on the current bar:
          1. Update max_price extreme from bar HIGH (intrabar peak).
          2. Add new virtual position(s) when HIGH >= last_entry_price + grid_size.
             Using HIGH instead of close ensures a candle that touches a grid
             level intrabar adds the position even if it closes below that level.
          3. Recompute exit trigger after any adds.
        """
        cfg = self.config

        # 1. Track extreme using intrabar HIGH; update grid_size if dynamic mode
        if self._max_price is None or high > self._max_price:
            self._max_price = high

        if cfg.dynamic_atr_grid:
            self._cycle_grid_size = grid_size

        # 2. Pyramiding: add positions for every grid level reached by HIGH
        while len(self._virtual_positions) < cfg.max_positions:
            next_add_price = self._last_entry_price + self._cycle_grid_size
            if high >= next_add_price:
                self._open_position(next_add_price)
            else:
                break

        # 3. Recalculate exit trigger (now based on intrabar high)
        self._recalc_exit_trigger()

    def _update_sell_cycle(self, low: float, grid_size: float) -> None:
        """
        Update a SHORT cycle on the current bar:
          1. Update min_price extreme from bar LOW (intrabar trough).
          2. Add new virtual position(s) when LOW <= last_entry_price - grid_size.
             Using LOW instead of close ensures a candle that touches a grid
             level intrabar adds the position even if it closes above that level.
          3. Recompute exit trigger after any adds.
        """
        cfg = self.config

        if self._min_price is None or low < self._min_price:
            self._min_price = low

        if cfg.dynamic_atr_grid:
            self._cycle_grid_size = grid_size

        while len(self._virtual_positions) < cfg.max_positions:
            next_add_price = self._last_entry_price - self._cycle_grid_size
            if low <= next_add_price:
                self._open_position(next_add_price)
            else:
                break

        self._recalc_exit_trigger()

    def _close_cycle(self, exit_price: float) -> float:
        """
        Close all virtual positions at ``exit_price``, accumulate P&L,
        clear cycle state, and return the cycle PnL.

        LONG  PnL = Σ (exit_price - entry_price)
        SHORT PnL = Σ (entry_price - exit_price)
        """
        if self._cycle_dir == "BUY":
            pnl = sum(exit_price - p["price"] for p in self._virtual_positions)
        else:
            pnl = sum(p["price"] - exit_price for p in self._virtual_positions)

        self._cumul_virtual_pnl += pnl

        # Clear cycle
        self._virtual_positions = []
        self._cycle_active = False
        self._last_entry_price = None
        self._max_price = None
        self._min_price = None

        return pnl

    def _next_direction(self, cycle_pnl: float, closed_dir: str) -> str:
        """
        Determine the direction of the next cycle.

        If ``direction_switch_on_loss`` is active AND the just-closed cycle was
        a loser, flip direction.  Otherwise stay in the preferred direction.
        """
        cfg = self.config
        if cfg.direction_switch_on_loss and cycle_pnl < 0:
            # Flip
            flipped = "SELL" if closed_dir == "BUY" else "BUY"
            return flipped
        # Stay
        return closed_dir

    # ─── on_bar ──────────────────────────────────────────────────

    def on_bar(self, index: int, data: pd.DataFrame) -> str | tuple:
        cfg = self.config

        # Minimum bars required before indicators are ready
        min_bars = max(
            cfg.atr_period,
            cfg.ema_period if cfg.trend_filter == "ema_slope" else 0,
        ) + 2

        close = float(data["close"].iloc[index])
        high  = float(data["high"].iloc[index])
        low   = float(data["low"].iloc[index])

        # Not enough data yet
        if len(data) < min_bars:
            self._exit_trigger_history.append(None)
            self._virtual_pnl_history.append(None)
            return "HOLD"

        # ── Compute indicators (no lookahead: data only up to current bar) ──
        atr_arr = self._compute_atr(data, cfg.atr_period)
        atr_val  = float(atr_arr[index]) if not np.isnan(atr_arr[index]) else None

        if cfg.trend_filter == "ema_slope":
            ema_arr = self._compute_ema(data["close"], cfg.ema_period)
        else:
            ema_arr = np.full(len(data), np.nan)

        grid_size = (atr_val * cfg.atr_multiplier) if atr_val is not None else None

        # ── No active cycle — look for entry ────────────────────────────────
        if not self._cycle_active:
            if grid_size is None:
                self._exit_trigger_history.append(None)
                self._virtual_pnl_history.append(None)
                return "HOLD"

            want_long  = self._trend_up(index, data, ema_arr)
            want_short = self._trend_down(index, data, ema_arr)

            # Respect trade_direction constraint
            can_long  = cfg.trade_direction in ("both", "long_only")
            can_short = cfg.trade_direction in ("both", "short_only")

            # If we have a preferred direction from direction_switch logic, honour it
            if self._preferred_dir == "SELL":
                want_long = False          # override trend to match requested flip
            elif self._preferred_dir == "BUY":
                want_short = False

            if want_long and can_long:
                self._start_buy_cycle(close, grid_size)
                self._exit_trigger_history.append(self._exit_trigger)
                self._virtual_pnl_history.append(None)
                return "BUY"

            if want_short and can_short:
                self._start_sell_cycle(close, grid_size)
                self._exit_trigger_history.append(self._exit_trigger)
                self._virtual_pnl_history.append(None)
                return "SELL"

            self._exit_trigger_history.append(None)
            self._virtual_pnl_history.append(None)
            return "HOLD"

        # ── Active BUY cycle ─────────────────────────────────────────────────
        if self._cycle_dir == "BUY":

            # Exit check FIRST (close price breaches trailing stop)
            if self._exit_trigger is not None and close <= self._exit_trigger:
                cycle_pnl     = self._close_cycle(close)
                closed_dir    = "BUY"
                next_dir      = self._next_direction(cycle_pnl, closed_dir)

                self._exit_trigger_history.append(None)
                self._virtual_pnl_history.append(round(self._cumul_virtual_pnl, 6))

                if grid_size is None:
                    # Cannot open a new cycle without ATR; use SELL to close engine pos
                    return "SELL"

                # Immediate re-entry in the determined direction
                can_long  = cfg.trade_direction in ("both", "long_only")
                can_short = cfg.trade_direction in ("both", "short_only")

                if next_dir == "BUY" and can_long:
                    self._start_buy_cycle(close, grid_size)
                    self._exit_trigger_history[-1] = self._exit_trigger
                    return "BUY"

                if next_dir == "SELL" and can_short:
                    self._start_sell_cycle(close, grid_size)
                    self._exit_trigger_history[-1] = self._exit_trigger
                    return "SELL"

                # Direction constraint prevents re-entry → close the engine position
                return "SELL"

            # Update levels (add positions if HIGH reached next grid, track max)
            effective_grid = grid_size if (cfg.dynamic_atr_grid and grid_size) else self._cycle_grid_size
            self._update_buy_cycle(high, effective_grid)

            self._exit_trigger_history.append(self._exit_trigger)
            self._virtual_pnl_history.append(round(self._cumul_virtual_pnl, 6))
            return "BUY"   # engine: already in BUY → hold

        # ── Active SELL cycle ────────────────────────────────────────────────
        if self._cycle_dir == "SELL":

            if self._exit_trigger is not None and close >= self._exit_trigger:
                cycle_pnl     = self._close_cycle(close)
                closed_dir    = "SELL"
                next_dir      = self._next_direction(cycle_pnl, closed_dir)

                self._exit_trigger_history.append(None)
                self._virtual_pnl_history.append(round(self._cumul_virtual_pnl, 6))

                if grid_size is None:
                    return "BUY"

                can_long  = cfg.trade_direction in ("both", "long_only")
                can_short = cfg.trade_direction in ("both", "short_only")

                if next_dir == "SELL" and can_short:
                    self._start_sell_cycle(close, grid_size)
                    self._exit_trigger_history[-1] = self._exit_trigger
                    return "SELL"

                if next_dir == "BUY" and can_long:
                    self._start_buy_cycle(close, grid_size)
                    self._exit_trigger_history[-1] = self._exit_trigger
                    return "BUY"

                return "BUY"

            effective_grid = grid_size if (cfg.dynamic_atr_grid and grid_size) else self._cycle_grid_size
            self._update_sell_cycle(low, effective_grid)

            self._exit_trigger_history.append(self._exit_trigger)
            self._virtual_pnl_history.append(round(self._cumul_virtual_pnl, 6))
            return "SELL"

        # Fallback (should never reach here)
        self._exit_trigger_history.append(None)
        self._virtual_pnl_history.append(None)
        return "HOLD"

    # ─── Indicator overlay ───────────────────────────────────────

    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        """
        Returns chart overlays for the frontend:

        - EMA {period}          — trend filter line (if ema_slope filter active)
        - Exit Trigger          — ratcheting trailing stop staircase
        - Virtual P&L (cumul.)  — cumulative real P&L of all virtual positions

        Parameters
        ----------
        data : pd.DataFrame
            Full OHLC dataset (same as used during ``on_bar`` loop).

        Returns
        -------
        dict
            Keys are overlay names, values are equal-length lists of
            ``float | None`` aligned to ``data``.
        """
        cfg = self.config
        n   = len(data)

        def _pad(lst: list, length: int) -> list:
            """Pad or trim a list to exactly ``length`` elements."""
            result = list(lst)
            while len(result) < length:
                result.append(None)
            return result[:length]

        result: dict = {}

        # EMA trend-filter line
        if cfg.trend_filter == "ema_slope":
            ema_full = self._compute_ema(data["close"], cfg.ema_period)
            result[f"EMA {cfg.ema_period}"] = [
                None if np.isnan(v) else round(float(v), 6) for v in ema_full
            ]

        # Ratcheting trailing stop
        result["Exit Trigger"] = _pad(self._exit_trigger_history, n)

        # Cumulative multi-position P&L
        result["Virtual P&L (cumul.)"] = _pad(self._virtual_pnl_history, n)

        return result
