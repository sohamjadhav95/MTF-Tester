"""
Indicator Functions
====================
Standalone indicator math extracted from strategy files.
These can be reused by any strategy or module.
"""

import numpy as np
import pandas as pd


def compute_ema(series: pd.Series, period: int) -> np.ndarray:
    """
    Standard Exponential Moving Average.
    EMA[i] = price * k + EMA[i-1] * (1 - k), k = 2/(period+1)
    First EMA value = SMA of first 'period' bars.
    """
    values = series.values.astype(float)
    ema = np.full(len(values), np.nan)
    k = 2.0 / (period + 1)

    if len(values) < period:
        return ema

    ema[period - 1] = np.mean(values[:period])
    for i in range(period, len(values)):
        ema[i] = values[i] * k + ema[i - 1] * (1 - k)

    return ema


def compute_sma(series: pd.Series, period: int) -> np.ndarray:
    """Simple Moving Average."""
    values = series.values.astype(float)
    sma = np.full(len(values), np.nan)
    for i in range(period - 1, len(values)):
        sma[i] = np.mean(values[i - period + 1: i + 1])
    return sma


def compute_atr(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int,
) -> np.ndarray:
    """
    Average True Range (Wilder's method, same as Pine atr()).
    """
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


def compute_rsi(series: pd.Series, period: int = 14) -> np.ndarray:
    """Relative Strength Index."""
    values = series.values.astype(float)
    n = len(values)
    rsi = np.full(n, np.nan)

    if n < period + 1:
        return rsi

    changes = np.diff(values)
    gains = np.where(changes > 0, changes, 0)
    losses = np.where(changes < 0, -changes, 0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100 - (100 / (1 + rs))

    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100 - (100 / (1 + rs))

    return rsi


def compute_bollinger_bands(
    series: pd.Series, period: int = 20, std_dev: float = 2.0
) -> tuple:
    """
    Bollinger Bands.
    Returns (upper, middle, lower) as numpy arrays.
    """
    middle = compute_sma(series, period)
    values = series.values.astype(float)
    n = len(values)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)

    for i in range(period - 1, n):
        std = np.std(values[i - period + 1: i + 1], ddof=1)
        upper[i] = middle[i] + std_dev * std
        lower[i] = middle[i] - std_dev * std

    return upper, middle, lower
