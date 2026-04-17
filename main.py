import sys
import os
import threading
from multiprocessing import Process
from data_collector.ticks_buffer import master_df

# Add the project root (parent of this file's directory) to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connect_mt5 import connect_mt5, disconnect_mt5

# Connect MT5
connect_mt5()

# Start master_df
master_df()

'''
Whole workflow
'''


# Disconnect MT5
disconnect_mt5()