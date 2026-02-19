"""
Data Provider Module
Fetches OHLCV historical data from MT5.
"""

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime


# MT5 timeframe constants mapping
TIMEFRAME_MT5 = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}


def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    date_from: datetime,
    date_to: datetime,
) -> pd.DataFrame:
    """
    Fetch OHLCV data from MT5 for the given symbol and timeframe.
    
    Args:
        symbol: Trading symbol (e.g. "EURUSD")
        timeframe: Timeframe string (e.g. "H1", "M15")
        date_from: Start datetime
        date_to: End datetime
    
    Returns:
        DataFrame with columns: time, open, high, low, close, tick_volume, spread
    
    Raises:
        ValueError: If timeframe is invalid or no data returned
    """
    tf = TIMEFRAME_MT5.get(timeframe)
    if tf is None:
        raise ValueError(
            f"Invalid timeframe '{timeframe}'. "
            f"Valid options: {list(TIMEFRAME_MT5.keys())}"
        )

    # Ensure the symbol is available in MarketWatch
    selected = mt5.symbol_select(symbol, True)
    if not selected:
        raise ValueError(
            f"Symbol '{symbol}' not found or could not be selected in MT5"
        )

    # Fetch rates
    rates = mt5.copy_rates_range(symbol, tf, date_from, date_to)

    if rates is None or len(rates) == 0:
        error = mt5.last_error()
        raise ValueError(
            f"No data returned for {symbol} {timeframe} "
            f"from {date_from} to {date_to}. MT5 error: {error}"
        )

    # Convert to DataFrame
    df = pd.DataFrame(rates)

    # Convert time from unix timestamp to datetime
    df["time"] = pd.to_datetime(df["time"], unit="s")

    # Rename columns for clarity
    df = df.rename(columns={
        "tick_volume": "volume",
    })

    # Keep only the columns we need
    df = df[["time", "open", "high", "low", "close", "volume", "spread"]]

    # Reset index
    df = df.reset_index(drop=True)

    return df
