# test_lookahead.py — run from project root
import sys; sys.path.insert(0, 'backend')
import pandas as pd, numpy as np
from strategies._template import BaseStrategy, TF_DURATION

# Build M1 across two H4 windows (bin 08:00-11:59, bin 12:00-15:59)
# Window A: strong up-move (100 -> 120). Window B: strong down-move (120 -> 80).
times = pd.date_range('2024-01-01 09:00', '2024-01-01 16:59', freq='1min')
closes = np.concatenate([np.linspace(100, 120, 240), np.linspace(120, 80, 240)])
df = pd.DataFrame({
    'time': times, 'open': closes, 'high': closes, 'low': closes,
    'close': closes, 'volume': np.ones(len(times)), 'spread': 0,
})

class Probe(BaseStrategy):
    name='probe'
    def on_bar(self,i,d): return 'HOLD'

p = Probe()
h4 = p._resample(df, '4h')
old = p._m1_to_htf_index(df['time'], h4['time'])
new = p._m1_to_completed_htf_index(df['time'], h4['time'], TF_DURATION['H4'])

print(f"H4 bars after resample+drop: {len(h4)}")
for i, row in h4.iterrows():
    print(f"  H4[{i}] open={row['time']} close={row['close']:.2f}")

# Key M1 bars to inspect
print("\nM1 index | time     | OLD h_idx | NEW h_idx | OLD sees | NEW sees")
for m1_idx in [0, 60, 119, 120, 180, 239, 240, 300, 479]:
    t = df.iloc[m1_idx]['time'].strftime('%H:%M')
    oh, nh = old[m1_idx], new[m1_idx]
    o_close = f"{h4.iloc[oh]['close']:.2f}" if 0 <= oh < len(h4) else "n/a"
    n_close = f"{h4.iloc[nh]['close']:.2f}" if 0 <= nh < len(h4) else "n/a"
    print(f"  {m1_idx:5d}  | {t}    |    {oh:3d}    |    {nh:3d}    |  {o_close:6s}  |  {n_close:6s}")
