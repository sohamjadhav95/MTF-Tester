"""
Edge-Stress Test Strategy — Boundary & Fault Verifier
======================================================
A single strategy file that, via its `mode` config field, exercises every
failure and boundary condition in the platform. Upload ONCE, then launch
it multiple times with different `mode` values to probe each area.

MODES — launch one scanner per mode, verify expected behavior:

    normal
        Baseline. Fires BUY at bar index 100, 200, 300, ... with SL/TP.
        Verifies: signals flow, no regressions vs Heartbeat.

    crash_on_bar
        Runs cleanly for `crash_every_n_bars` calls, then raises ValueError on
        every subsequent call so faults are CONSECUTIVE. After 5 consecutive
        faults the engine HALTS the scanner and emits SCANNER_ERROR.
        Verifies:
          • SCANNER_ERROR arrives on WebSocket
          • Toast appears
          • Footer errors counter increments per fault
          • After 5 consecutive faults: scanner card LED turns to led-error
          • After halt, no further processing

    crash_on_start
        Raises in on_start() during historical backfill.
        Verifies: backend logs the failure, scanner still registers but
                  emits no signals. UI should NOT lock up.

    bad_signal_string
        Returns an unknown string like "MAYBE_BUY" every `cadence_bars`. The
        parser raises ValueError on unknown strings — counts as a bar fault.
        Faults are NON-consecutive (cadence-spaced), so the scanner does NOT
        halt. Verifies error-counter wiring without triggering halt.

    bad_signal_tuple
        Returns a malformed tuple ("BUY", "not-a-number", "also-bad") on
        EVERY bar. Parser raises on the float conversion; faults accumulate
        consecutively; scanner halts after 5 consecutive faults. Verifies
        the halt path through the parser exception branch.

    rapid_fire
        Emits BUY on EVERY bar. Alternates with SELL via flip. Stresses:
          • Signal panel row insertion
          • WebSocket throughput
          • Dedup by signal ID
          • Auto-executor dedup by already-open-position check

    sl_only
        Every signal has SL but no TP. Tests validator branch.

    tp_only
        Every signal has TP but no SL. Tests validator branch.

    no_sl_tp
        No SL, no TP. Raw market order. Tests the simplest order path.

    impossible_sl
        Every signal has an SL at an impossible distance (e.g. inverted).
        Validator should REJECT with ValueError; auto-executor should
        increment fail count and eventually auto-disable.

    long_only
        BUY signals every 50 bars, no SELL. Tests direction filter.

    short_only
        SELL signals every 50 bars, no BUY. Mirror test.

    flip_flop
        BUY/SELL on consecutive bars (every 2 bars). Tests the direction-
        flip logic in auto-executor — opening a BUY should close any prior
        SELL on same scanner+symbol before opening the new BUY.

    same_signal_repeat
        BUY every single bar. Auto-executor should NOT place a new order
        if a position with matching AUTO:{scanner_id}:{sig_id[:8]} tag
        already exists — it dedupes on signal_id.

    state_accumulator
        Uses self.state['counter'] across on_update calls to fire BUY only
        after 3 consecutive HTF bars (simulated by bar count). Verifies the
        P0-A fix: state must PERSIST across polls — if live resets on every
        poll (old bug), this mode will never fire a signal. If backtest
        and live both work, state-persistence is confirmed.

    slow_on_bar
        on_bar sleeps 200ms to simulate expensive computation. Verifies the
        engine handles slow strategies without data loss.

    warmup_check
        Returns BUY on bar index 0. If this signal reaches the panel
        during live scanning, warmup suppression is broken. The engine
        should silently absorb early bars and emit NO signals for the
        first 1440 M1 bars (1 day).

USAGE
-----
Upload this file once. In MTF Strategy panel, select "Edge Stress Test" and
set `mode` to the scenario you want to probe. Use a different Session Name
for each (e.g. "Edge — crash_on_bar", "Edge — rapid_fire") so scanner cards
and nav entries stay distinct.

RECOMMENDED SYMBOL
------------------
Use a cheap demo symbol (EURUSD on a demo MT5) for modes that place real
orders. The crash/fault modes don't need auto-trade enabled.

SAFETY
------
NEVER enable auto-trade on `rapid_fire`, `impossible_sl`, or `same_signal_repeat`
on a live account. Demo only.
"""

from __future__ import annotations

import time
from typing import Literal, Any
import numpy as np
import pandas as pd
from pydantic import Field

from ._template import BaseStrategy, StrategyConfig, Signal, HOLD


MODES = Literal[
    "normal",
    "crash_on_bar",
    "crash_on_start",
    "bad_signal_string",
    "bad_signal_tuple",
    "rapid_fire",
    "sl_only",
    "tp_only",
    "no_sl_tp",
    "impossible_sl",
    "long_only",
    "short_only",
    "flip_flop",
    "same_signal_repeat",
    "state_accumulator",
    "slow_on_bar",
    "warmup_check",
]


class EdgeStressConfig(StrategyConfig):
    mode: MODES = Field(
        "normal",
        description="Which edge case to exercise — see file docstring for details."
    )
    crash_every_n_bars: int = Field(
        10, ge=1, le=1_000_000,
        description="For crash_on_bar mode: raise every Nth bar call"
    )
    cadence_bars: int = Field(
        50, ge=1, le=10_000,
        description="Base cadence for modes that use periodic signals"
    )
    pip_size: float = Field(
        0.0001, gt=0, le=1.0,
        description="Pip size for this symbol (EURUSD=0.0001, XAUUSD=0.1)"
    )
    state_threshold: int = Field(
        3, ge=1, le=100,
        description="For state_accumulator mode: fire after N consecutive on_update calls"
    )
    slow_sleep_ms: int = Field(
        200, ge=0, le=5000,
        description="For slow_on_bar mode: ms to sleep inside on_bar"
    )


class EdgeStressTest(BaseStrategy):
    name = "Edge Stress Test"
    description = "Mode-driven strategy that probes every failure boundary. Launch with different modes."
    config_model = EdgeStressConfig

    def __init__(self, settings=None):
        super().__init__(settings)
        # Counters used by several modes — initialized fresh on each instance
        self._bar_call_count = 0
        self._last_direction: str | None = None  # for flip_flop

    def on_start(self, data: pd.DataFrame) -> None:
        cfg = self.config

        # Initialize persistent state (engine must NOT wipe this on poll)
        if "update_count" not in self.state:
            self.state["update_count"] = 0

        if cfg.mode == "crash_on_start":
            raise RuntimeError("crash_on_start mode: intentional failure in on_start()")

        closes = data["close"].values.astype(float)
        self._cache = {"closes": closes, "n": len(data)}

    def on_update(self, new_bars: pd.DataFrame, data: pd.DataFrame) -> None:
        """
        Incremental update. For state_accumulator mode, bump a counter that
        must persist across calls. Other modes just rebuild the cache.
        """
        self.state["update_count"] = self.state.get("update_count", 0) + 1
        # Rebuild cache (cheap — these are reference arrays only)
        self._cache = {
            "closes": data["close"].values.astype(float),
            "n": len(data),
        }

    def _sl_tp(self, direction: str, price: float, sl_pips: float, tp_pips: float) -> tuple:
        cfg = self.config
        sl = None
        tp = None
        if sl_pips > 0:
            sl = price - sl_pips * cfg.pip_size if direction == "BUY" else price + sl_pips * cfg.pip_size
            if sl <= 0:
                sl = None
        if tp_pips > 0:
            tp = price + tp_pips * cfg.pip_size if direction == "BUY" else price - tp_pips * cfg.pip_size
            if tp <= 0:
                tp = None
        return sl, tp

    def on_bar(self, index: int, data: pd.DataFrame) -> Any:
        cfg = self.config
        self._bar_call_count += 1

        if not self._cache:
            return HOLD

        closes = self._cache["closes"]
        if index >= len(closes):
            return HOLD
        price = float(closes[index])

        # ─── crash_on_bar ─────────────────────────────────────────
        # Behavior: run cleanly for `crash_every_n_bars` calls, then raise on
        # every subsequent call. This produces consecutive faults, which the
        # engine counts toward the MAX_BAR_FAULTS=5 halt threshold.
        if cfg.mode == "crash_on_bar":
            if self._bar_call_count > cfg.crash_every_n_bars:
                raise ValueError(
                    f"crash_on_bar mode: intentional failure at call #{self._bar_call_count} (bar {index})"
                )
            return HOLD

        # ─── bad_signal_string ────────────────────────────────────
        if cfg.mode == "bad_signal_string":
            if index % cfg.cadence_bars == 0:
                return "MAYBE_BUY"   # unknown — parser should map to HOLD
            return HOLD

        # ─── bad_signal_tuple ─────────────────────────────────────
        # Returns malformed tuple on EVERY call so faults are consecutive and
        # the scanner halts after MAX_BAR_FAULTS=5. Tests the halt path.
        if cfg.mode == "bad_signal_tuple":
            return ("BUY", "not-a-number", "also-bad")  # malformed — parser raises ValueError

        # ─── rapid_fire — every bar, alternating ──────────────────
        if cfg.mode == "rapid_fire":
            direction = "BUY" if self._bar_call_count % 2 == 1 else "SELL"
            sl, tp = self._sl_tp(direction, price, 20, 40)
            return Signal(direction=direction, sl=sl, tp=tp,
                          metadata={"mode": "rapid_fire", "call": self._bar_call_count})

        # ─── sl_only ──────────────────────────────────────────────
        if cfg.mode == "sl_only":
            if index % cfg.cadence_bars != 0:
                return HOLD
            sl = price - 20 * cfg.pip_size
            return Signal(direction="BUY", sl=sl, tp=None,
                          metadata={"mode": "sl_only"})

        # ─── tp_only ──────────────────────────────────────────────
        if cfg.mode == "tp_only":
            if index % cfg.cadence_bars != 0:
                return HOLD
            tp = price + 40 * cfg.pip_size
            return Signal(direction="BUY", sl=None, tp=tp,
                          metadata={"mode": "tp_only"})

        # ─── no_sl_tp ─────────────────────────────────────────────
        if cfg.mode == "no_sl_tp":
            if index % cfg.cadence_bars != 0:
                return HOLD
            return Signal(direction="BUY", sl=None, tp=None,
                          metadata={"mode": "no_sl_tp"})

        # ─── impossible_sl (inverted: BUY with SL above entry) ────
        if cfg.mode == "impossible_sl":
            if index % cfg.cadence_bars != 0:
                return HOLD
            bad_sl = price + 20 * cfg.pip_size   # SL ABOVE entry for a BUY — nonsense
            return Signal(direction="BUY", sl=bad_sl, tp=None,
                          metadata={"mode": "impossible_sl"})

        # ─── long_only / short_only ───────────────────────────────
        if cfg.mode == "long_only":
            if index % cfg.cadence_bars != 0:
                return HOLD
            sl, tp = self._sl_tp("BUY", price, 20, 40)
            return Signal(direction="BUY", sl=sl, tp=tp, metadata={"mode": "long_only"})

        if cfg.mode == "short_only":
            if index % cfg.cadence_bars != 0:
                return HOLD
            sl, tp = self._sl_tp("SELL", price, 20, 40)
            return Signal(direction="SELL", sl=sl, tp=tp, metadata={"mode": "short_only"})

        # ─── flip_flop — BUY/SELL on consecutive cadence points ───
        if cfg.mode == "flip_flop":
            if index % cfg.cadence_bars != 0:
                return HOLD
            self._last_direction = "SELL" if self._last_direction == "BUY" else "BUY"
            sl, tp = self._sl_tp(self._last_direction, price, 30, 60)
            return Signal(direction=self._last_direction, sl=sl, tp=tp,
                          metadata={"mode": "flip_flop"})

        # ─── same_signal_repeat — BUY every cadence, same direction ──
        if cfg.mode == "same_signal_repeat":
            if index % cfg.cadence_bars != 0:
                return HOLD
            sl, tp = self._sl_tp("BUY", price, 20, 40)
            return Signal(direction="BUY", sl=sl, tp=tp, metadata={"mode": "same_signal_repeat"})

        # ─── state_accumulator — relies on self.state persistence ─
        if cfg.mode == "state_accumulator":
            # Only fire if state counter has advanced past threshold
            if self.state.get("update_count", 0) < cfg.state_threshold:
                return HOLD
            # Fire once per cadence past threshold
            if index % cfg.cadence_bars != 0:
                return HOLD
            sl, tp = self._sl_tp("BUY", price, 20, 40)
            return Signal(direction="BUY", sl=sl, tp=tp,
                          metadata={"mode": "state_accumulator",
                                    "update_count": self.state["update_count"]})

        # ─── slow_on_bar ──────────────────────────────────────────
        if cfg.mode == "slow_on_bar":
            time.sleep(cfg.slow_sleep_ms / 1000.0)
            if index % cfg.cadence_bars != 0:
                return HOLD
            sl, tp = self._sl_tp("BUY", price, 20, 40)
            return Signal(direction="BUY", sl=sl, tp=tp, metadata={"mode": "slow_on_bar"})

        # ─── warmup_check — fire immediately at bar 0 ─────────────
        if cfg.mode == "warmup_check":
            if index == 0:
                return Signal(direction="BUY", sl=None, tp=None,
                              metadata={"mode": "warmup_check",
                                        "note": "if you see this signal, warmup suppression is broken"})
            return HOLD

        # ─── normal (default) ─────────────────────────────────────
        if index % cfg.cadence_bars != 0:
            return HOLD
        sl, tp = self._sl_tp("BUY", price, 20, 40)
        return Signal(direction="BUY", sl=sl, tp=tp, metadata={"mode": "normal"})
