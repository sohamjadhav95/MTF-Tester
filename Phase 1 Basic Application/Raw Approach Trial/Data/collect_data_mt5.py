import time
import os
import sys
import pandas as pd
from datetime import datetime
import MetaTrader5 as mt5

# Mapping timeframes to seconds for correct candle timing calculations
TIMEFRAME_SECONDS = {
    mt5.TIMEFRAME_M1: 60,
    mt5.TIMEFRAME_M2: 120,
    mt5.TIMEFRAME_M3: 180,
    mt5.TIMEFRAME_M4: 240,
    mt5.TIMEFRAME_M5: 300,
    mt5.TIMEFRAME_M10: 600,
    mt5.TIMEFRAME_M12: 720,
    mt5.TIMEFRAME_M15: 900,
    mt5.TIMEFRAME_M20: 1200,
    mt5.TIMEFRAME_M30: 1800,
    mt5.TIMEFRAME_H1: 3600,
    mt5.TIMEFRAME_H2: 7200,
    mt5.TIMEFRAME_H3: 10800,
    mt5.TIMEFRAME_H4: 14400,
    mt5.TIMEFRAME_H6: 21600,
    mt5.TIMEFRAME_H8: 28800,
    mt5.TIMEFRAME_H12: 43200,
    mt5.TIMEFRAME_D1: 86400,
}

def get_historical_ohlc(symbol, timeframe, num_bars):
    """Fetch structured historical OHLC data from MT5."""
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, num_bars)
    if rates is None or len(rates) == 0:
        print(f"Failed to get historical data for {symbol}")
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    return df[['open', 'high', 'low', 'close', 'tick_volume']]

def start_live_tick_to_ohlc(symbol, timeframe, csv_filename, history_bars=100):
    """Subscribes to live ticks, builds OHLC data in real-time, and updates CSV."""

    # 1. Check if MT5 is already initialized and connected
    is_connected = False
    if mt5.initialize():
        term_info = mt5.terminal_info()
        if term_info is not None and term_info.connected:
            is_connected = True

    # 2. If not connected, use the centralized connection script
    if not is_connected:
        print("MT5 is not connected. Executing centralized connect_mt5.py...")
        main_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Main'))
        if main_dir not in sys.path:
            sys.path.insert(0, main_dir)
        
        # Because connect_mt5.py executes its connection block at the module level,
        # simply importing it will log us onto the broker using your central credentials.
        import connect_mt5
        
        # Verify connection again post-execution
        if not mt5.initialize() or not mt5.terminal_info().connected:
            print("Still failed to connect after running central connection script.")
            return

    # Ensure symbol is visible in Market Watch
    if not mt5.symbol_select(symbol, True):
        print(f"Failed to select symbol '{symbol}'. Error: {mt5.last_error()}")
        return

    tf_seconds = TIMEFRAME_SECONDS.get(timeframe)
    if tf_seconds is None:
        print("Unsupported timeframe selected. Please add it to TIMEFRAME_SECONDS mapping.")
        return

    print(f"Fetching {history_bars} historical bars for {symbol}...")
    df = get_historical_ohlc(symbol, timeframe, history_bars)
    if df is None:
        return

    # Export initial history frame
    df.to_csv(csv_filename)
    print(f"Saved initial historical data to: {csv_filename}")

    # Variables for tracking
    last_candle_time = df.index[-1]
    last_tick_time_msc = 0 
    
    print(f"\nStarting live tick tracking... Press Ctrl+C to stop.\n")
    
    try:
        while True:
            # Briefly sleep to avoid maxing out CPU (10ms polling rate)
            time.sleep(0.01)
            
            # Fetch the most recent tick
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                continue
                
            # Use explicitly the ask price for building the candles
            tick_price = tick.ask
            
            # If the tick is exactly the one we already processed, skip
            if tick.time_msc == last_tick_time_msc:
                continue
                
            last_tick_time_msc = tick.time_msc
            
            # Calculate the candle timestamp for this tick (rounded to TF boundary)
            candle_timestamp = pd.to_datetime((tick.time // tf_seconds) * tf_seconds, unit='s')
            
            # Check if this tick crosses the boundary into a new candle
            if candle_timestamp > last_candle_time:
                # Log closed candle results
                print(f"\n[Candle Closed] {last_candle_time} | O:{df.at[last_candle_time, 'open']} H:{df.at[last_candle_time, 'high']} L:{df.at[last_candle_time, 'low']} C:{df.at[last_candle_time, 'close']}")
                
                # Starting a new row for the new candle
                new_row = pd.DataFrame({
                    'open': [tick_price],
                    'high': [tick_price],
                    'low': [tick_price],
                    'close': [tick_price],
                    'tick_volume': [1]
                }, index=[candle_timestamp])
                
                # Exclude empty rows and concatenate
                df = pd.concat([df, new_row])
                last_candle_time = candle_timestamp
                print(f"--- Started New Candle: {candle_timestamp} ---")
                
            else:
                # We are still within the same candle time bounds, modify existing candle
                current_high = df.at[last_candle_time, 'high']
                current_low = df.at[last_candle_time, 'low']
                
                df.at[last_candle_time, 'high'] = max(current_high, tick_price)
                df.at[last_candle_time, 'low'] = min(current_low, tick_price)
                df.at[last_candle_time, 'close'] = tick_price
                df.at[last_candle_time, 'tick_volume'] += 1
            
            # Overwrite the CSV file with our newly shaped dataframe
            df.to_csv(csv_filename)
            
            # Provide live feed status linearly on the console
            print(f"Live Tick: {tick_price:.5f} | Forming Candle: {last_candle_time.strftime('%H:%M:%S')} => Close Updated: {df.at[last_candle_time, 'close']:.5f} (Vol: {df.at[last_candle_time, 'tick_volume']}) ", end='\r')

    except KeyboardInterrupt:
        print("\n\nStopped live tick collection.")
        mt5.shutdown()

if __name__ == '__main__':
    # Settings (Feel free to configure these to what you want)
    SYMBOL = "EURUSDm"
    TIMEFRAME = mt5.TIMEFRAME_M1
    HISTORY_BARS = 100
    
    # Target CSV to save output
    CSV_FILE = os.path.join(os.path.dirname(__file__), f"{SYMBOL}_M1.csv")
    
    start_live_tick_to_ohlc(SYMBOL, TIMEFRAME, CSV_FILE, history_bars=HISTORY_BARS)
