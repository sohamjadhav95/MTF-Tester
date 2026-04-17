import pandas as pd
import time

import pandas as pd
import time
import os

TICK_FILE = r"E:\Projects\Freelancing\MTF-Tester\data_collector\monitor\live_ticks.csv"
OHLC_FILE = r"E:\Projects\Freelancing\MTF-Tester\data_collector\monitor\ohlc_tf.csv"


def initialize(tf):
    df = pd.read_csv(TICK_FILE)
    df["time"] = pd.to_datetime(df["time"])
    df["price"] = (df["bid"] + df["ask"]) / 2
    df["candle_time"] = df["time"].dt.floor(tf)

    ohlc = df.groupby("candle_time")["price"].agg(
        open="first",
        high="max",
        low="min",
        close="last"
    ).reset_index()
    forming_candle = ohlc.iloc[-1].to_dict()
    ohlc.drop(ohlc.index[-1], inplace=True)     # drop last row; avoid inconsistancy
    ohlc.to_csv(OHLC_FILE, index=False)

    return len(df), forming_candle


def run(tf):
    last_index, current_candle = initialize(tf)

    while True:
        df = pd.read_csv(TICK_FILE)
        new_ticks = df.iloc[last_index:]
        last_index = len(df)

        for _, tick in new_ticks.iterrows():
            timestamp = pd.to_datetime(tick["time"])
            price = (tick["bid"] + tick["ask"]) / 2
            candle_time = timestamp.floor(tf)

            if candle_time == pd.to_datetime(current_candle["candle_time"]):
                current_candle["high"] = max(current_candle["high"], price)
                current_candle["low"] = min(current_candle["low"], price)
                current_candle["close"] = price

            else:
                # append finished candle
                new_row = pd.DataFrame([current_candle])
                new_row.to_csv(OHLC_FILE, mode='a', header=not os.path.exists(OHLC_FILE), index=False)

                # start new candle
                current_candle = {
                    "candle_time": candle_time,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price
                }

        time.sleep(0.1)

# ── Timeframe functions ───────────────────────────────────────────────────────

def TF_1M():
    run("1min")

def TF_5M():
    run("5min")

def TF_15M():
    run("15min")

def TF_30M():
    run("30min")

def TF_1H():
    run("1h")

def TF_4H():
    run("4h")

def TF_1D():
    run("1d")


if __name__ == "__main__":
    # run ticks buffer in background
    TF_1M()