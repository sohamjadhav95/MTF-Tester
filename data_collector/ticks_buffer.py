import time
import MetaTrader5 as mt5
import pandas as pd
import os
from datetime import datetime, timedelta

from get_data import fetch_historic_ticks, fetch_new_ticks
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connect_mt5 import connect_mt5
from get_data import fetch_historic_ticks, fetch_new_ticks


def master_df(symbol, days_back, csv_file):
    # ── Step 1: Load historic ticks ───────────────────────────────────────────────
    start_date = datetime.now() - timedelta(days=days_back)
    print(start_date)
    master_df = fetch_historic_ticks(symbol, start_date)

    print(f"\nMaster DF shape: {master_df.shape}")
    print(master_df.tail())


    # ── Step 2: Write CSV header once ─────────────────────────────────────────────
    # Start CSV fresh each run — only live ticks go in here
    master_df.to_csv(CSV_FILE, index=False)

    print(f"\nCSV created: {CSV_FILE}")
    print("Starting live tick stream. Watch the CSV or the prints below.\n")


    # ── Step 3: Live loop ─────────────────────────────────────────────────────────
    last_time = master_df['time'].iloc[-1]   # pointer — where live picks up from

    while True:
        new_ticks = fetch_new_ticks(SYMBOL, last_time)

        if not new_ticks.empty:
            # Append to master
            # Master DF if TRUE source of data for strategy
            master_df = pd.concat([master_df, new_ticks], ignore_index=True)

            # Append to CSV
            new_ticks.to_csv(CSV_FILE, mode='a', header=False, index=False)

            # Update pointer
            last_time = new_ticks['time'].iloc[-1]

            # Print what arrived
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] "
                f"+{len(new_ticks)} ticks | "
                f"Total: {len(master_df)} | "
                f"Last bid: {new_ticks['bid'].iloc[-1]} | "
                f"Last ask: {new_ticks['ask'].iloc[-1]}")

        time.sleep(1)


if __name__ == "__main__":
    connect_mt5()

    # ── Settings ──────────────────────────────────────────────────────────────────
    SYMBOL    = "XAUUSDm"   # change to your symbol
    DAYS_BACK = 4           # how many days of historic ticks to load
    CSV_FILE  = r"E:\Projects\Freelancing\MTF-Tester\data_collector\monitor\live_ticks.csv"

    master_df(SYMBOL, DAYS_BACK, CSV_FILE)