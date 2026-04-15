"""
Strategy Template v3 — Phase 2 Dead Template Foundation
========================================================
All strategies must subclass `BaseStrategy` and define a `StrategyConfig`
Pydantic model. Drop filled template files into backend/strategies/ and restart.

Two-Layer Architecture:
  Layer 1 (Signal):  on_start() pre-computes → on_bar() reads cache → returns signal
  Layer 2 (Visual):  get_indicator_data() returns IndicatorPlot list for chart rendering

The strategy is INDEPENDENT from charts — it declares its own timeframe,
computes its own indicators, and generates signals autonomously.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field as dc_field
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple, Type

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════
# BASE CONFIG — All strategies extend this
# ═══════════════════════════════════════════════════════════════════

class StrategyConfig(BaseModel):
    """
    Base configuration for all strategies.
    Subclass with typed Field() definitions. The resulting Pydantic model
    becomes the single source of truth for validation, defaults, and
    JSON Schema generation.
    """

    model_config = {"extra": "forbid"}

    # Every strategy declares which timeframe it generates signals on.
    # This makes the strategy independent from chart timeframes.
    entry_timeframe: str = Field(
        "H1",
        description="Timeframe for signal generation (e.g. M1, M5, M15, H1, H4, D1)",
    )


# ═══════════════════════════════════════════════════════════════════
# INDICATOR PLOT — Visualization descriptor for chart rendering
# ═══════════════════════════════════════════════════════════════════

@dataclass
class IndicatorPlot:
    """
    Describes one visual element to draw on the chart.

    Pane options:
      "price"    → overlaid on the candlestick chart
      "separate" → new pane below the chart

    Type options:
      "line"      → continuous line (EMA, SMA, BB mid)
      "histogram" → bar histogram (MACD hist, volume delta)
      "level"     → horizontal line at fixed price (S/R)
      "markers"   → dots/arrows on bars (signal points)
      "band"      → filled area between two lines (BB, Keltner)
      "zone"      → horizontal shaded region (S/D zones)
    """
    id:          str                              # unique identifier
    label:       str                              # display name
    pane:        str = "price"                    # "price" | "separate"
    type:        str = "line"                     # "line" | "histogram" | "band" | "markers" | "level" | "zone"
    color:       str = "#3b82f6"                  # hex color
    values:      list = dc_field(default_factory=list)  # [{time, value}, ...]
    # Band type extras
    band_upper:  Optional[list] = None            # [{time, value}, ...] for band upper
    band_lower:  Optional[list] = None            # [{time, value}, ...] for band lower
    # Zone type extras (values contain zone_top, zone_bottom, zone_type, status)
    zones:       Optional[list] = None            # [{from, to, color}, ...] for RSI-style zones
    line_width:  int = 1


# ═══════════════════════════════════════════════════════════════════
# BASE STRATEGY — Abstract class all strategies inherit
# ═══════════════════════════════════════════════════════════════════

class BaseStrategy(ABC):
    """
    Abstract base class for every trading strategy.

    To create a strategy:
      1. Subclass StrategyConfig with typed fields
      2. Subclass BaseStrategy, set name, description, config_model
      3. Implement on_start() to pre-compute indicators
      4. Implement on_bar() to generate signals from cache
      5. Implement get_indicator_data() for chart overlays
      6. Drop the file into backend/strategies/ and restart

    The system discovers, validates, and serves it automatically.
    """

    # ── Class-level metadata (override in subclass) ─────────────
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    version: ClassVar[str] = "1.0"
    strategy_type: ClassVar[str] = "indicator"   # "indicator"|"zone"|"pattern"|"mtf"|"hybrid"
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

        # Cache dict — populated by on_start(), read by on_bar()
        self._cache: Dict[str, Any] = {}
        self._warmup: int = 50

    # ── Schema helper ───────────────────────────────────────────
    @classmethod
    def get_json_schema(cls) -> dict:
        """Return the full JSON Schema for this strategy's config."""
        return cls.config_model.model_json_schema()

    # ── Lifecycle hooks ─────────────────────────────────────────

    def on_start(self, data: pd.DataFrame) -> None:
        """
        Called ONCE before the bar loop begins.
        Pre-compute ALL indicators here and store in self._cache.
        on_bar() should ONLY read from self._cache — never compute.
        """
        self._warmup = self._calculate_warmup(self.config)

    def on_finish(self, data: pd.DataFrame) -> None:
        """Called once after the bar loop ends. Override if needed."""
        pass

    # ── Core contract ───────────────────────────────────────────
    @abstractmethod
    def on_bar(self, index: int, data: pd.DataFrame) -> str | tuple:
        """
        Called on each bar. Returns the trade signal.
        ONLY reads from self._cache — never computes indicators here.

        Returns:
            "BUY"  | "SELL" | "HOLD"
            ("BUY",  sl_price, tp_price)
            ("SELL", sl_price, tp_price)
            ("BUY",  None,     tp_price)  — TP only
            ("BUY",  sl_price, None)      — SL only
        """
        ...

    # ── Indicator overlay ──────────────────────────────────────
    def get_indicator_data(self, data: pd.DataFrame) -> list:
        """
        Return IndicatorPlot list for chart rendering.
        Called AFTER on_start() with the full dataset.
        Each IndicatorPlot = one visual element on the chart.
        """
        return []

    # ═══════════════════════════════════════════════════════════════
    # BUILT-IN HELPERS — Available to all strategies via self._xxx()
    # ═══════════════════════════════════════════════════════════════

    # ── SL/TP Helpers ─────────────────────────────────────────────

    def _sl_price(self, direction: str, index: int, data: pd.DataFrame) -> Optional[float]:
        """Calculate SL price based on config sl_mode."""
        cfg = self.config
        sl_mode = getattr(cfg, "sl_mode", "none")
        close = float(data.iloc[index]["close"])
        low   = float(data.iloc[index]["low"])
        high  = float(data.iloc[index]["high"])

        if sl_mode == "none":
            return None

        if sl_mode == "fixed_pips":
            sl_pips = getattr(cfg, "sl_pips", None)
            if not sl_pips:
                return None
            point = getattr(self, "_point", 0.00001)
            dist = sl_pips * point * 10
            return (close - dist) if direction == "BUY" else (close + dist)

        if sl_mode == "atr":
            atr_arr = self._cache.get("atr")
            if atr_arr is None:
                return None
            atr_val = atr_arr[index]
            if np.isnan(atr_val):
                return None
            mult = getattr(cfg, "sl_atr_mult", 1.5) or 1.5
            return (close - atr_val * mult) if direction == "BUY" else (close + atr_val * mult)

        if sl_mode == "candle_hl":
            return low if direction == "BUY" else high

        if sl_mode == "zone":
            zones = self._cache.get("zones", [])
            for zone in zones:
                if zone.get("status") == "triggered":
                    return zone["distal"]
            return None

        if sl_mode == "swing":
            support    = self._cache.get("support")
            resistance = self._cache.get("resistance")
            if direction == "BUY" and support is not None:
                return float(support[index])
            if direction == "SELL" and resistance is not None:
                return float(resistance[index])
            return None

        return None

    def _tp_price(self, direction: str, sl: Optional[float], entry: float) -> Optional[float]:
        """Calculate TP price from SL distance × RR ratio."""
        if sl is None:
            return None
        rr = getattr(self.config, "rr_ratio", 2.0) or 2.0
        sl_dist = abs(entry - sl)
        if sl_dist == 0:
            return None
        return (entry + sl_dist * rr) if direction == "BUY" else (entry - sl_dist * rr)

    # ── Indicator Calculation Helpers ─────────────────────────────

    @staticmethod
    def _ema(series: pd.Series, period: int) -> np.ndarray:
        values = series.values.astype(float)
        ema = np.full(len(values), np.nan)
        if len(values) < period:
            return ema
        k = 2.0 / (period + 1)
        ema[period - 1] = np.mean(values[:period])
        for i in range(period, len(values)):
            ema[i] = values[i] * k + ema[i - 1] * (1 - k)
        return ema

    @staticmethod
    def _sma(series: pd.Series, period: int) -> np.ndarray:
        return series.rolling(period).mean().values

    @staticmethod
    def _rsi(series: pd.Series, period: int = 14) -> np.ndarray:
        delta = series.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        return (100 - (100 / (1 + rs))).values

    @staticmethod
    def _atr(data: pd.DataFrame, period: int = 14) -> np.ndarray:
        high  = data["high"].values.astype(float)
        low   = data["low"].values.astype(float)
        close = data["close"].values.astype(float)
        tr = np.maximum(high - low,
             np.maximum(np.abs(high - np.roll(close, 1)),
                        np.abs(low  - np.roll(close, 1))))
        tr[0] = high[0] - low[0]
        atr = np.full(len(tr), np.nan)
        atr[period - 1] = np.mean(tr[:period])
        for i in range(period, len(tr)):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        return atr

    @staticmethod
    def _true_range(data: pd.DataFrame) -> np.ndarray:
        high  = data["high"].values.astype(float)
        low   = data["low"].values.astype(float)
        close = data["close"].values.astype(float)
        tr = np.maximum(high - low,
             np.maximum(np.abs(high - np.roll(close, 1)),
                        np.abs(low  - np.roll(close, 1))))
        tr[0] = high[0] - low[0]
        return tr

    @staticmethod
    def _bollinger(series: pd.Series, period: int = 20,
                   std: float = 2.0) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        mid = series.rolling(period).mean()
        sigma = series.rolling(period).std()
        return (mid + std * sigma).values, mid.values, (mid - std * sigma).values

    @staticmethod
    def _macd(series: pd.Series, fast: int = 12, slow: int = 26,
              signal: int = 9) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        sig = macd.ewm(span=signal, adjust=False).mean()
        hist = macd - sig
        return macd.values, sig.values, hist.values

    @staticmethod
    def _stochastic(data: pd.DataFrame, k_period: int = 14,
                    d_period: int = 3) -> Tuple[np.ndarray, np.ndarray]:
        low_min = data["low"].rolling(k_period).min()
        high_max = data["high"].rolling(k_period).max()
        k = 100 * (data["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
        d = k.rolling(d_period).mean()
        return k.values, d.values

    @staticmethod
    def _cci(data: pd.DataFrame, period: int = 20) -> np.ndarray:
        tp = (data["high"] + data["low"] + data["close"]) / 3
        sma = tp.rolling(period).mean()
        mad = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - np.mean(x))))
        return ((tp - sma) / (0.015 * mad)).values

    @staticmethod
    def _swing_highs(data: pd.DataFrame, lookback: int = 20) -> np.ndarray:
        """Returns resistance level at each bar (last confirmed swing high)."""
        highs = data["high"].values.astype(float)
        result = np.full(len(highs), np.nan)
        last = np.nan
        for i in range(lookback, len(highs)):
            window = highs[i - lookback: i]
            if highs[i - 1] == np.max(window):
                last = highs[i - 1]
            result[i] = last
        return result

    @staticmethod
    def _swing_lows(data: pd.DataFrame, lookback: int = 20) -> np.ndarray:
        """Returns support level at each bar (last confirmed swing low)."""
        lows = data["low"].values.astype(float)
        result = np.full(len(lows), np.nan)
        last = np.nan
        for i in range(lookback, len(lows)):
            window = lows[i - lookback: i]
            if lows[i - 1] == np.min(window):
                last = lows[i - 1]
            result[i] = last
        return result

    @staticmethod
    def _wma(series: pd.Series, period: int) -> np.ndarray:
        weights = np.arange(1, period + 1, dtype=float)
        weights /= weights.sum()
        return np.convolve(series.values.astype(float), weights[::-1], mode='full')[:len(series)]

    @staticmethod
    def _dema(series: pd.Series, period: int) -> np.ndarray:
        ema1 = series.ewm(span=period, adjust=False).mean()
        ema2 = ema1.ewm(span=period, adjust=False).mean()
        return (2 * ema1 - ema2).values

    @staticmethod
    def _tema(series: pd.Series, period: int) -> np.ndarray:
        ema1 = series.ewm(span=period, adjust=False).mean()
        ema2 = ema1.ewm(span=period, adjust=False).mean()
        ema3 = ema2.ewm(span=period, adjust=False).mean()
        return (3 * ema1 - 3 * ema2 + ema3).values

    @staticmethod
    def _vwap(data: pd.DataFrame) -> np.ndarray:
        tp = (data["high"] + data["low"] + data["close"]) / 3
        vol = data["volume"].replace(0, np.nan)
        return (tp * vol).cumsum() / vol.cumsum().values

    @staticmethod
    def _supertrend(data: pd.DataFrame, period: int = 10,
                    multiplier: float = 3.0) -> Tuple[np.ndarray, np.ndarray]:
        """Returns (supertrend_line, direction) where direction: 1=bullish, -1=bearish."""
        high  = data["high"].values.astype(float)
        low   = data["low"].values.astype(float)
        close = data["close"].values.astype(float)
        n = len(close)

        # ATR
        tr = np.maximum(high - low,
             np.maximum(np.abs(high - np.roll(close, 1)),
                        np.abs(low  - np.roll(close, 1))))
        tr[0] = high[0] - low[0]
        atr = np.full(n, np.nan)
        atr[period - 1] = np.mean(tr[:period])
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        basic_upper = (high + low) / 2 + multiplier * atr
        basic_lower = (high + low) / 2 - multiplier * atr

        final_upper = np.full(n, np.nan)
        final_lower = np.full(n, np.nan)
        supertrend  = np.full(n, np.nan)
        direction   = np.full(n, np.nan)

        for i in range(period, n):
            final_upper[i] = basic_upper[i] if (
                basic_upper[i] < final_upper[i-1] or close[i-1] > final_upper[i-1]
            ) else final_upper[i-1]
            final_lower[i] = basic_lower[i] if (
                basic_lower[i] > final_lower[i-1] or close[i-1] < final_lower[i-1]
            ) else final_lower[i-1]

            if np.isnan(supertrend[i-1]) or supertrend[i-1] == final_upper[i-1]:
                supertrend[i] = final_upper[i] if close[i] <= final_upper[i] else final_lower[i]
            else:
                supertrend[i] = final_lower[i] if close[i] >= final_lower[i] else final_upper[i]

            direction[i] = -1 if supertrend[i] == final_upper[i] else 1

        return supertrend, direction

    @staticmethod
    def _ichimoku(data: pd.DataFrame) -> Dict[str, np.ndarray]:
        """Returns Tenkan, Kijun, Senkou A, Senkou B, Chikou."""
        high = data["high"]
        low  = data["low"]
        close = data["close"]
        tenkan   = ((high.rolling(9).max() + low.rolling(9).min()) / 2).values
        kijun    = ((high.rolling(26).max() + low.rolling(26).min()) / 2).values
        senkou_a = pd.Series((tenkan + kijun) / 2).shift(26).values
        senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26).values
        chikou   = close.shift(-26).values
        return {"tenkan": tenkan, "kijun": kijun,
                "senkou_a": senkou_a, "senkou_b": senkou_b, "chikou": chikou}

    # ── Chart Formatting Helper ───────────────────────────────────

    @staticmethod
    def _to_chart_values(data: pd.DataFrame, arr: np.ndarray) -> list:
        """Convert numpy array to [{time, value}, ...] for frontend charts."""
        result = []
        for i, val in enumerate(arr):
            if val is not None and not (isinstance(val, float) and np.isnan(val)):
                t = data.iloc[i]["time"]
                result.append({
                    "time": t.isoformat() if hasattr(t, "isoformat") else str(t),
                    "value": round(float(val), 6),
                })
        return result

    # ── Warmup Calculator ─────────────────────────────────────────

    @staticmethod
    def _calculate_warmup(cfg) -> int:
        """Auto-calculate minimum bars needed from all period settings."""
        periods = []
        for attr in vars(cfg):
            val = getattr(cfg, attr)
            if isinstance(val, int) and "period" in attr and val:
                periods.append(val)
        return max(periods) + 1 if periods else 50

    # ── Signal Broadcast (used by engine) ─────────────────────────

    def get_last_signal(self) -> Optional[dict]:
        """
        Returns the last signal dict for the automated trading system.
        Called by MTFLiveEngine after on_bar() returns a signal.
        Structure: {direction, sl, tp, entry_price, bar_time, pattern}
        """
        return getattr(self, "_last_signal", None)
