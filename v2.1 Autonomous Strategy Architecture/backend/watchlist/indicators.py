"""
Chart Indicator Computation
============================
Pure server-side indicator computation.  Every function receives the SAME
pd.DataFrame that produces candle bars, ensuring zero data inconsistency.

Supported indicators:
  overlay  : SMA, EMA, Bollinger Bands, VWAP
  separate : RSI, MACD, Volume

All functions return JSON-serializable dicts with {time, value} lists
whose timestamps match the candle bar timestamps exactly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# ── Indicator Registry (metadata only) ─────────────────────────────────
# Shared with the frontend for the picker UI via GET endpoint.

INDICATOR_REGISTRY: List[Dict[str, Any]] = [
    {
        "id": "sma",
        "name": "SMA",
        "fullName": "Simple Moving Average",
        "category": "trend",
        "pane": "overlay",
        "icon": "📈",
        "defaultSettings": {
            "period": 20,
            "source": "close",
            "color": "#2196F3",
            "lineWidth": 2,
        },
        "settingsSchema": [
            {"key": "period", "label": "Period", "type": "number", "min": 1, "max": 500, "step": 1},
            {"key": "source", "label": "Source", "type": "select", "options": ["open", "high", "low", "close"]},
            {"key": "color",  "label": "Color",  "type": "color"},
            {"key": "lineWidth", "label": "Line Width", "type": "number", "min": 1, "max": 5, "step": 1},
        ],
    },
    {
        "id": "ema",
        "name": "EMA",
        "fullName": "Exponential Moving Average",
        "category": "trend",
        "pane": "overlay",
        "icon": "📉",
        "defaultSettings": {
            "period": 20,
            "source": "close",
            "color": "#FF9800",
            "lineWidth": 2,
        },
        "settingsSchema": [
            {"key": "period", "label": "Period", "type": "number", "min": 1, "max": 500, "step": 1},
            {"key": "source", "label": "Source", "type": "select", "options": ["open", "high", "low", "close"]},
            {"key": "color",  "label": "Color",  "type": "color"},
            {"key": "lineWidth", "label": "Line Width", "type": "number", "min": 1, "max": 5, "step": 1},
        ],
    },
    {
        "id": "bb",
        "name": "BB",
        "fullName": "Bollinger Bands",
        "category": "trend",
        "pane": "overlay",
        "icon": "📊",
        "defaultSettings": {
            "period": 20,
            "stdDev": 2.0,
            "source": "close",
            "color": "#9C27B0",
            "lineWidth": 1,
        },
        "settingsSchema": [
            {"key": "period", "label": "Period", "type": "number", "min": 2, "max": 500, "step": 1},
            {"key": "stdDev", "label": "Std Dev", "type": "number", "min": 0.1, "max": 10, "step": 0.1},
            {"key": "source", "label": "Source", "type": "select", "options": ["open", "high", "low", "close"]},
            {"key": "color",  "label": "Color",  "type": "color"},
            {"key": "lineWidth", "label": "Line Width", "type": "number", "min": 1, "max": 5, "step": 1},
        ],
    },
    {
        "id": "vwap",
        "name": "VWAP",
        "fullName": "Volume Weighted Average Price",
        "category": "trend",
        "pane": "overlay",
        "icon": "⚖️",
        "defaultSettings": {
            "color": "#00BCD4",
            "lineWidth": 2,
        },
        "settingsSchema": [
            {"key": "color",  "label": "Color",  "type": "color"},
            {"key": "lineWidth", "label": "Line Width", "type": "number", "min": 1, "max": 5, "step": 1},
        ],
    },
    {
        "id": "rsi",
        "name": "RSI",
        "fullName": "Relative Strength Index",
        "category": "oscillator",
        "pane": "separate",
        "icon": "📐",
        "defaultSettings": {
            "period": 14,
            "overbought": 70,
            "oversold": 30,
            "color": "#E040FB",
            "lineWidth": 2,
        },
        "settingsSchema": [
            {"key": "period", "label": "Period", "type": "number", "min": 2, "max": 200, "step": 1},
            {"key": "overbought", "label": "Overbought", "type": "number", "min": 50, "max": 100, "step": 1},
            {"key": "oversold",   "label": "Oversold",   "type": "number", "min": 0,  "max": 50,  "step": 1},
            {"key": "color",  "label": "Color",  "type": "color"},
            {"key": "lineWidth", "label": "Line Width", "type": "number", "min": 1, "max": 5, "step": 1},
        ],
    },
    {
        "id": "macd",
        "name": "MACD",
        "fullName": "Moving Average Convergence Divergence",
        "category": "oscillator",
        "pane": "separate",
        "icon": "📶",
        "defaultSettings": {
            "fastPeriod": 12,
            "slowPeriod": 26,
            "signalPeriod": 9,
            "macdColor": "#2196F3",
            "signalColor": "#FF9800",
            "lineWidth": 2,
        },
        "settingsSchema": [
            {"key": "fastPeriod",   "label": "Fast Period",   "type": "number", "min": 2, "max": 200, "step": 1},
            {"key": "slowPeriod",   "label": "Slow Period",   "type": "number", "min": 2, "max": 200, "step": 1},
            {"key": "signalPeriod", "label": "Signal Period", "type": "number", "min": 2, "max": 200, "step": 1},
            {"key": "macdColor",    "label": "MACD Color",    "type": "color"},
            {"key": "signalColor",  "label": "Signal Color",  "type": "color"},
            {"key": "lineWidth", "label": "Line Width", "type": "number", "min": 1, "max": 5, "step": 1},
        ],
    },
    {
        "id": "volume",
        "name": "Volume",
        "fullName": "Volume",
        "category": "volume",
        "pane": "separate",
        "icon": "📊",
        "defaultSettings": {
            "maPeriod": 20,
            "upColor": "#22c55e80",
            "downColor": "#ef444480",
            "maColor": "#FF9800",
        },
        "settingsSchema": [
            {"key": "maPeriod", "label": "MA Period", "type": "number", "min": 1, "max": 200, "step": 1},
            {"key": "upColor",   "label": "Up Color",   "type": "color"},
            {"key": "downColor", "label": "Down Color", "type": "color"},
            {"key": "maColor",   "label": "MA Color",   "type": "color"},
        ],
    },
]


# ── Time Formatting Helper ─────────────────────────────────────────────
# Matches the exact format used in WatchlistEngine.get_historical_bars()
# so timestamps are identical between candle bars and indicator values.

def _fmt_time(t) -> str:
    """Convert a DataFrame time value to UTC ISO string (matching bar format)."""
    time_str = t.isoformat() if hasattr(t, "isoformat") else str(t)
    if not time_str.endswith("Z") and "+" not in time_str:
        time_str += "Z"
    return time_str


def _to_time_value_list(df: pd.DataFrame, series: pd.Series) -> List[Dict]:
    """
    Convert a pandas Series to [{time, value}, ...] using timestamps
    from the same DataFrame.  Skips NaN values so the frontend doesn't
    need to handle null checks.
    """
    result = []
    for i in range(len(series)):
        val = series.iat[i]
        if pd.notna(val):
            result.append({
                "time": _fmt_time(df.iat[i, df.columns.get_loc("time")]),
                "value": round(float(val), 6),
            })
    return result


def _to_histogram_list(df: pd.DataFrame, series: pd.Series, pos_color: str = "#22c55e80", neg_color: str = "#ef444480") -> List[Dict]:
    """Convert series to histogram-style [{time, value, color}, ...]."""
    result = []
    for i in range(len(series)):
        val = series.iat[i]
        if pd.notna(val):
            result.append({
                "time": _fmt_time(df.iat[i, df.columns.get_loc("time")]),
                "value": round(float(val), 6),
                "color": pos_color if val >= 0 else neg_color,
            })
    return result


# ── Dispatcher ─────────────────────────────────────────────────────────

def compute_indicator(df: pd.DataFrame, indicator_type: str, settings: dict) -> dict:
    """
    Compute indicator from the given DataFrame.
    Returns a dict with the indicator type, computed data series, and
    rendering metadata.

    This is the only function the engine calls — it dispatches internally.
    """
    dispatch = {
        "sma": _compute_sma,
        "ema": _compute_ema,
        "bb": _compute_bb,
        "vwap": _compute_vwap,
        "rsi": _compute_rsi,
        "macd": _compute_macd,
        "volume": _compute_volume,
    }

    fn = dispatch.get(indicator_type)
    if fn is None:
        raise ValueError(f"Unknown indicator type: {indicator_type}")

    return fn(df, settings)


# ── Individual Indicator Computations ──────────────────────────────────
# Every function receives the same df used for candle bars.


def _compute_sma(df: pd.DataFrame, settings: dict) -> dict:
    period = int(settings.get("period", 20))
    source = settings.get("source", "close")
    values = df[source].rolling(window=period, min_periods=period).mean()
    return {
        "series": {
            "main": _to_time_value_list(df, values),
        },
        "pane": "overlay",
    }


def _compute_ema(df: pd.DataFrame, settings: dict) -> dict:
    period = int(settings.get("period", 20))
    source = settings.get("source", "close")
    values = df[source].ewm(span=period, adjust=False, min_periods=period).mean()
    return {
        "series": {
            "main": _to_time_value_list(df, values),
        },
        "pane": "overlay",
    }


def _compute_bb(df: pd.DataFrame, settings: dict) -> dict:
    period = int(settings.get("period", 20))
    std_dev = float(settings.get("stdDev", 2.0))
    source = settings.get("source", "close")

    sma = df[source].rolling(window=period, min_periods=period).mean()
    std = df[source].rolling(window=period, min_periods=period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std

    return {
        "series": {
            "middle": _to_time_value_list(df, sma),
            "upper": _to_time_value_list(df, upper),
            "lower": _to_time_value_list(df, lower),
        },
        "pane": "overlay",
    }


def _compute_vwap(df: pd.DataFrame, settings: dict) -> dict:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, np.nan)  # avoid div-by-zero
    cum_vol = vol.cumsum()
    cum_tp_vol = (typical * vol).cumsum()
    vwap = cum_tp_vol / cum_vol
    return {
        "series": {
            "main": _to_time_value_list(df, vwap),
        },
        "pane": "overlay",
    }


def _compute_rsi(df: pd.DataFrame, settings: dict) -> dict:
    period = int(settings.get("period", 14))
    source = settings.get("source", "close")
    overbought = float(settings.get("overbought", 70))
    oversold = float(settings.get("oversold", 30))

    delta = df[source].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))

    return {
        "series": {
            "main": _to_time_value_list(df, rsi),
        },
        "levels": [
            {"value": overbought, "color": "#ef4444", "style": "dashed"},
            {"value": oversold,   "color": "#22c55e", "style": "dashed"},
            {"value": 50,         "color": "#64748b", "style": "dotted"},
        ],
        "pane": "separate",
        "scaleRange": {"min": 0, "max": 100},
    }


def _compute_macd(df: pd.DataFrame, settings: dict) -> dict:
    fast = int(settings.get("fastPeriod", 12))
    slow = int(settings.get("slowPeriod", 26))
    signal = int(settings.get("signalPeriod", 9))
    source = settings.get("source", "close")

    fast_ema = df[source].ewm(span=fast, adjust=False, min_periods=fast).mean()
    slow_ema = df[source].ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line

    return {
        "series": {
            "macd": _to_time_value_list(df, macd_line),
            "signal": _to_time_value_list(df, signal_line),
            "histogram": _to_histogram_list(df, histogram, "#26a69a80", "#ef535080"),
        },
        "pane": "separate",
    }


def _compute_volume(df: pd.DataFrame, settings: dict) -> dict:
    ma_period = int(settings.get("maPeriod", 20))
    up_color = settings.get("upColor", "#22c55e80")
    down_color = settings.get("downColor", "#ef444480")

    vol_ma = df["volume"].rolling(window=ma_period, min_periods=1).mean()

    # Volume bars colored by candle direction
    vol_bars = []
    for i in range(len(df)):
        row = df.iloc[i]
        vol_val = row["volume"]
        if pd.notna(vol_val):
            color = up_color if row["close"] >= row["open"] else down_color
            vol_bars.append({
                "time": _fmt_time(row["time"]),
                "value": float(vol_val),
                "color": color,
            })

    return {
        "series": {
            "bars": vol_bars,
            "ma": _to_time_value_list(df, vol_ma),
        },
        "pane": "separate",
    }
