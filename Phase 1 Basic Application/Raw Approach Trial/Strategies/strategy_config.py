import sys
import os
import MetaTrader5 as mt5

# Adjust sys.path so Python can find horizontal folders like 'Data' and 'Main'
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from Data.collect_data_mt5 import start_live_tick_to_ohlc

# Timeframes

M1 = mt5.TIMEFRAME_M1
M2 = mt5.TIMEFRAME_M2
M3 = mt5.TIMEFRAME_M3
M4 = mt5.TIMEFRAME_M4
M5 = mt5.TIMEFRAME_M5
M10 = mt5.TIMEFRAME_M10
M12 = mt5.TIMEFRAME_M12
M15 = mt5.TIMEFRAME_M15
M20 = mt5.TIMEFRAME_M20
M30 = mt5.TIMEFRAME_M30
H1 = mt5.TIMEFRAME_H1
H2 = mt5.TIMEFRAME_H2
H3 = mt5.TIMEFRAME_H3
H4 = mt5.TIMEFRAME_H4
H6 = mt5.TIMEFRAME_H6
H8 = mt5.TIMEFRAME_H8
H12 = mt5.TIMEFRAME_H12
D1 = mt5.TIMEFRAME_D1

def get_symbol_and_timeframe():
    symbol = str(input("Enter the symbol: ")).strip()
    timeframe_str = str(input("Enter the timeframe (e.g. M1, H1): ")).strip().upper()
    
    # Place the CSV strictly in the Data folder implicitly
    csv_filename = os.path.join(parent_dir, "Data", f"{symbol}_{timeframe_str}.csv")
    history_bars = 500
    
    # Dynamically fetch the integer constant from your global variables above (e.g., M1, H1)
    timeframe_val = globals().get(timeframe_str)
    if timeframe_val is None:
        print(f"Warning: Timeframe '{timeframe_str}' not recognized. Defaulting to M1.")
        timeframe_val = mt5.TIMEFRAME_M1
        
    return symbol, timeframe_val, csv_filename, history_bars

def get_data():
    symbol, timeframe, csv_filename, history_bars = get_symbol_and_timeframe()
    start_live_tick_to_ohlc(symbol, timeframe, csv_filename, history_bars)

    filepath = os.path.join(parent_dir, "Data", f"{symbol}_{timeframe}.csv")
    return filepath

get_data()