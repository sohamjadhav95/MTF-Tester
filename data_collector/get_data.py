import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta


def fetch_historic_ticks(symbol, start_date, end_date=None):
    """Fetch all ticks between start_date and end_date from MT5."""
    if end_date is None:
        end_date = datetime.now()

    ticks = mt5.copy_ticks_range(symbol, start_date, end_date, mt5.COPY_TICKS_ALL)

    if ticks is None or len(ticks) == 0:
        print(f"No historic ticks returned. MT5 error: {mt5.last_error()}")
        return pd.DataFrame()

    df = pd.DataFrame(ticks)
    df['time'] = pd.to_datetime(df['time_msc'], unit='ms')
    df = df[['time', 'time_msc', 'bid', 'ask', 'last', 'volume', 'flags']]
    print(f"Historic loaded: {len(df)} ticks | {df['time'].iloc[0]} to {df['time'].iloc[-1]}")
    return df


def fetch_new_ticks(symbol, since_datetime):
    """Fetch ticks that arrived after since_datetime. Used inside the live loop."""
    fetch_from = since_datetime + timedelta(milliseconds=1)
    ticks = mt5.copy_ticks_from(symbol, fetch_from, 1000, mt5.COPY_TICKS_ALL)

    if ticks is None or len(ticks) == 0:
        return pd.DataFrame()

    df = pd.DataFrame(ticks)
    df['time'] = pd.to_datetime(df['time_msc'], unit='ms')
    df = df[['time', 'time_msc', 'bid', 'ask', 'last', 'volume', 'flags']]
    return df

if __name__ == "__main__":
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from connect_mt5 import connect_mt5
    connect_mt5()
    fetch_historic_ticks("XAUUSDm", datetime.now() - timedelta(days=10))