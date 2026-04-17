import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import threading
from multiprocessing import Process

from connect_mt5 import connect_mt5, disconnect_mt5
from data_collector.ticks_buffer import master_df
from data_collector.timeframe import TF_1M

# Connect MT5
connect_mt5()

# Start master_df
p1 = threading.Thread(
    target=master_df,
    args=('XAUUSDm', 4, r"E:\Projects\Freelancing\MTF-Tester\data_collector\monitor\live_ticks.csv")
)

p2 = threading.Thread(target=TF_1M)

p1.start()
time.sleep(10)      # Wait for CSV creation
p2.start()

'''
Whole workflow
'''


# Disconnect MT5
#disconnect_mt5()