# MTF Tester User Guide

Welcome to the **MTF Tester**. This guide will walk you through the end-to-end usage of the platform, from connecting your broker to deploying fully automated multi-timeframe trading strategies.

---

## 1. Initial Setup

### Connecting to MetaTrader 5
MTF Tester requires the MetaTrader 5 terminal to be installed and running on your local machine. 

1. Launch the MTF Tester application (via `start.bat`).
2. Open `http://127.0.0.1:8000/` in your browser.
3. On the Dashboard, locate the **MT5 Connection** card.
4. Enter your MT5 login credentials and server name.
5. Click **Connect**. 
   > **Note:** The header and footer will turn green and display "MT5: Connected" once successful. Your account equity will immediately reflect in the top metrics bar.

---

## 2. The Dashboard

The Dashboard is your main control center. It contains several key elements:

- **Top Header:** Displays real-time Server Time (UTC), Network Latency, Account Equity, and your current Risk Guard status. The **Kill-Switch** is also located here.
- **Active Instances:** Shows all currently running live Scanners. You can stop scanners or toggle their auto-trade capability directly from these cards.
- **Activity Feed (Right Pane):** A rolling log of the last 20 events (signals fired, orders placed, risk breaches).
- **Open Positions (Right Pane):** Live view of your currently open trades with real-time floating PnL. Includes a **Close All** button for emergencies.
- **Command Palette:** Press `Cmd+K` (or `Ctrl+K`) anywhere in the app to quickly jump between panels or trigger the kill-switch.

---

## 3. Strategy Management

MTF Tester operates on a **Candles + Signals** philosophy. Strategies are simple `.py` files that ingest price data and emit `BUY`, `SELL`, or `HOLD` signals.

### Creating a Strategy via AI Builder
If you don't know how to code, you can use the built-in AI Strategy Builder.
1. Navigate to the **Create** panel via the left navigation menu.
2. Under the **Strategy Builder Prompt**, fill in the plain English description of your strategy (e.g., "Buy when the 10 EMA crosses above the 50 EMA on the 1-minute chart").
3. Click **Generate Prompt**.
4. Copy the generated prompt and paste it into an LLM (like ChatGPT or Claude). It includes all necessary boilerplate to generate a compatible `.py` file.

### Uploading a Strategy
1. Once you have a valid `.py` strategy file, go to the **Create** panel.
2. Drag and drop the `.py` file into the upload zone.
3. If valid, the strategy will immediately appear in the **Strategies** panel dropdown.

> [!TIP]
> For developers writing manual strategies, please refer to the [`STRATEGY_FORMAT.md`](backend/strategies/STRATEGY_FORMAT.md) for API usage, state management rules, and best practices.

---

## 4. Scanners & Backtesting

### Launching a Live Scanner
A Scanner is an active instance of a strategy running against a specific symbol and timeframe.

1. Navigate to the **Strategies** panel.
2. Select your uploaded strategy from the dropdown.
3. The UI will automatically generate input fields based on the strategy's configuration (e.g., `fast_period`, `rr_ratio`).
4. Fill in a **Session Name** (e.g., "EMA Pulse EURUSD") and select your target **Symbol** (e.g., `EURUSD`).
5. Click **Launch Scanner**.

The scanner will immediately backfill historical data and then transition to live polling. A new tab will open showing the scanner's live signal table and aggregated statistics.

### Historical Backtesting
Instead of launching live, you can test a strategy's historical performance.
1. Fill out the Strategy inputs just like you would for a live scanner.
2. Set your testing window.
3. Click the **Backtest** button. 
4. The system simulates a bar-by-bar progression to guarantee **zero look-ahead bias**.

---

## 5. Live Trading & Risk Management

### Automated Trading
You can allow a live Scanner to automatically execute its signals as real market orders.

> [!WARNING]  
> Always test automated trading on a **Demo Account** first.

1. Locate your running scanner under the **Active Instances** list on the Dashboard.
2. Toggle the **AUTO** switch.
3. Enter your desired trade volume (e.g., `0.01` lots).
4. Confirm the warning dialog.
The scanner card will now display an `AUTO` badge. The system will manage SL/TP automatically.

### Manual Trading
Need to place a quick manual trade?
1. Open the **Trading** panel from the left navigation.
2. Select the **Manual Order** tab.
3. Enter your Symbol, Volume, Direction (BUY/SELL).
4. Optionally configure your Stop Loss (SL) and Take Profit (TP) offsets.
5. Click **Place Order**.

### Risk Guard
To protect your account from significant drawdown, configure the Risk Guard:
1. Go to the **Trading** panel and select the **Risk Guard** tab.
2. Enable the **Risk Threshold** and set a percentage (e.g., `2.0%`).
3. Enable **Auto-close on breach**.
If your floating PnL ever drops below 2% of your total equity, MTF Tester will immediately execute a market close on **all open positions** and alert you.

### Emergency Kill-Switch
Located in the top header (and accessible via `Ctrl+K`), the **Kill-Switch** provides a hard stop.
When activated, it immediately halts all automated trade execution. (Note: Due to security designs, disabling the kill-switch requires manually editing the `.env` file and restarting the application).

---

## 6. Advanced Features & Troubleshooting

### Orphan Position Recovery
If the MTF Tester backend crashes or is restarted while auto-trades are open, the system will perform an automatic reconcile on startup.
- You will be greeted with an **Orphan Positions Detected** modal.
- These are positions that the MTF Tester opened previously but are no longer tracked by an active scanner.
- You must manually close these positions (via MT5 or the Dashboard) to prevent unmanaged trades.

### Scanner Errors and Halting
Strategies might encounter calculation errors (e.g., dividing by zero).
- If a strategy throws an error on a specific bar, you will see a toast notification and the error count in the footer will increase.
- **Max Faults:** If a scanner encounters 5 consecutive errors, it will enter a `HALTED` state. The LED on its card will turn red, and it will stop processing new bars to protect the system. You must stop and re-launch the scanner.

### The 10016 "Invalid Stops" Error
If your auto-trade fails with broker code `10016`, it usually means your strategy uses hard-coded pip distances for Stop Losses that don't match the symbol's digit scale (e.g., using Forex pip sizes on Crypto). 
**Fix:** Modify your strategy to use Volatility-based stops (like ATR) instead of fixed pips.
