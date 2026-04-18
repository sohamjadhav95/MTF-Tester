import pandas as pd
import numpy as np
import os
import time
from strategy_config import get_data

def calculate_atr(df, period=14):
    """Calculate the Average True Range."""
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(period).mean()

def apply_ema_crossover(df, fast_len=9, slow_len=21):
    """
    Apply EMA Crossover strategy logic.
    Returns Buy (1) and Sell (-1) signals along with TP and SL levels.
    """
    # Calculate Historic EMA
    df['EMA_Fast'] = df['close'].ewm(span=fast_len, adjust=False).mean()
    df['EMA_Slow'] = df['close'].ewm(span=slow_len, adjust=False).mean()
    
    # Calculate ATR for dynamic TP and SL
    df['ATR'] = calculate_atr(df, period=14)
    
    # Initialize Signal, SL, TP columns
    df['Signal'] = 0
    df['SL'] = np.nan
    df['TP'] = np.nan
    
    # Buy condition: Fast crosses above Slow
    buy_condition = (df['EMA_Fast'] > df['EMA_Slow']) & (df['EMA_Fast'].shift(1) <= df['EMA_Slow'].shift(1))
    
    # Sell condition: Fast crosses below Slow
    sell_condition = (df['EMA_Fast'] < df['EMA_Slow']) & (df['EMA_Fast'].shift(1) >= df['EMA_Slow'].shift(1))
    
    df.loc[buy_condition, 'Signal'] = 1
    df.loc[sell_condition, 'Signal'] = -1
    
    # Configure SL & TP multipliers (e.g. 1.5x ATR for SL, 3.0x ATR for TP)
    risk_multi = 1.5
    reward_multi = 3.0
    
    # For Buy Signals
    df.loc[buy_condition, 'SL'] = df['close'] - (df['ATR'] * risk_multi)
    df.loc[buy_condition, 'TP'] = df['close'] + (df['ATR'] * reward_multi)
    
    # For Sell Signals
    df.loc[sell_condition, 'SL'] = df['close'] + (df['ATR'] * risk_multi)
    df.loc[sell_condition, 'TP'] = df['close'] - (df['ATR'] * reward_multi)
    
    # Optionally drop ATR if you only want OHLC + EMA + Signals
    # df.drop(columns=['ATR'], inplace=True)
    
    return df

def main():
    # 1. Fetch data path (this will prompt for symbol and timeframe internally)
    # The start_live_tick_to_ohlc process gets started here in the background
    filepath = get_data()
    print(f"Using data file: {filepath}")
    
    base_name = os.path.basename(filepath)
    name_no_ext, _ = os.path.splitext(base_name)
    
    # Save the signals CSV in the same directory as the strategy script
    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_filename = os.path.join(current_dir, f"{name_no_ext}_EMA_Crossover_Signals.csv")
    
    print("Starting live signal generation loop. Press Ctrl+C to stop.")
    
    try:
        while True:
            # 2. Read OHLC data into pandas DataFrame
            if not os.path.exists(filepath):
                print(f"Waiting for {filepath} to be created...")
                time.sleep(1)
                continue
                
            try:
                df = pd.read_csv(filepath)
            except Exception as e:
                # Skip if the file is locked by the MT5 collection process temporarily
                time.sleep(0.1)
                continue
            
            if df.empty:
                time.sleep(1)
                continue
                
            # Ensure column names are lowercase to match calculation expectations
            df.columns = [c.lower() if c not in ['Time', 'Date'] else c for c in df.columns]
            
            # 3. Apply EMA Crossover logic
            fast_length = 9
            slow_length = 21
            df = apply_ema_crossover(df, fast_len=fast_length, slow_len=slow_length)
            
            # 4. Save results continuously
            df.to_csv(output_filename, index=False)
            print(f"[{time.strftime('%H:%M:%S')}] Updated live signals saved to: {output_filename}")
            
            # Pause before the next iteration to avoid maxing out the CPU
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nLive signal generation stopped.")

if __name__ == '__main__':
    main()
