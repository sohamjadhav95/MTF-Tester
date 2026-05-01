# MTF Tester v2.4 — End-to-End Test Runbook

**Purpose.** Two strategy files plus this runbook. Upload the strategies, follow the runbook in order, record pass/fail per step. At the end you'll have a checked-off confirmation that every feature in the platform works — or a precise list of what doesn't and where.

**Required before starting.** Zip from this session deployed, MT5 demo account credentials at hand, server started, browser on `http://127.0.0.1:8000`.

**Two files delivered alongside this runbook:**
- `test_heartbeat_strategy.py` — deterministic clock strategy, happy-path verifier
- `test_edge_stress_strategy.py` — mode-driven edge-case verifier

---

## Part 0 · Upload both strategies once

1. Open the app. Click **Create** in the left nav.
2. Drag `test_heartbeat_strategy.py` into the upload zone. Expect "✓ Uploaded" and it appears in the list.
3. Drag `test_edge_stress_strategy.py`. Same expectation.
4. Click **Strategies** in the left nav. The dropdown should now include:
    - Heartbeat Test
    - Edge Stress Test

If either fails to load with the error "strategy file invalid" or similar, stop here and report. This is a validator issue, not a test issue.

---

## Part 1 · Pre-flight UI checks (before touching strategies)

These verify the transformation fixes you just shipped.

### 1.1 — Header widgets (F-3, F-4, F-5, C-12, C-13)

Open a fresh browser tab on the app. With MT5 **disconnected**:

- [ ] **Brand "MTF"** visible top-left in white text (not transparent/invisible) — F-1 from round 1
- [ ] **Server time** ticks every second in UTC
- [ ] **Latency**: shows `--ms` with grey dot (not yet measured)
- [ ] **Equity**: shows `$0.00`
- [ ] **Risk chip**: shows `RISK: DISARMED` in muted color
- [ ] **Kill-switch button**: reads `● KILL-SW OFF` (assuming default .env)
- [ ] **⌘K button** clickable, cursor pointer on hover

### 1.2 — Footer (F-4, C-10, C-11)

- [ ] **MT5 indicator**: greyed out, reads "MT5: Disconnected"
- [ ] **Stats text**: "Scanners 0 | Signals today 0 | Auto-trades 0"
- [ ] **Errors counter**: "errors 0"
- [ ] **Version**: "v2.3.0" (or whatever the current label is)

### 1.3 — Connect to MT5

Dashboard → fill MT5 credentials → Connect. Expect:

- [ ] Success toast
- [ ] MT5 card badge → "Connected" (green)
- [ ] **Footer LED turns green pulsing** (F-4 live check)
- [ ] **Footer text: `MT5: <your-server-name>`**
- [ ] **Header equity updates** to real balance
- [ ] **Header PnL** shows $0.00 or current floating pnl
- [ ] **Right-pane ACCOUNT** section populates (equity, balance, free margin, floating)
- [ ] **Right-pane positions section**: shows "No open positions" empty state (icon + text)

### 1.4 — Wait 10 seconds (F-3 latency + poll)

- [ ] **Header latency** now shows a number (e.g. `12`) with green dot for <100ms local
- [ ] **Sparkline** under the equity numbers begins drawing (after 2+ data points)

### 1.5 — Kill-switch click (F-5)

- [ ] Click the kill-switch button in the header
- [ ] Modal opens titled "Emergency Kill-Switch"
- [ ] Modal explains: current state + "edit .env and restart" instructions
- [ ] Click Cancel → modal closes, no state change

### 1.6 — Command palette (F-5 + C-2)

- [ ] Press **⌘K** (or **Ctrl+K** on Windows)
- [ ] Palette opens with 5 commands listed
- [ ] Type "kill" → filters to the kill-switch command
- [ ] Enter → same modal as 1.5 opens
- [ ] ⌘K again → type "strat" → Enter → jumps to MTF Strategy panel (not silent no-op — this was C-2)
- [ ] ⌘K → type "dash" → Enter → returns to Dashboard
- [ ] Click outside or Esc closes the palette

**If any 1.x check fails**, stop and report before proceeding. Phase 1 fatals should all be resolved.

---

## Part 2 · Heartbeat — happy-path end-to-end

**Goal:** verify signal → chart → panel → auto-trade → close → accounting all work in real time with predictable outputs.

### 2.1 — Launch Heartbeat scanner

Strategies panel → fill:

| Field | Value |
|---|---|
| Session Name | `Heartbeat EURUSD` |
| Symbol | `EURUSD` (any liquid demo symbol — works on XAUUSD too because stops are ATR-scaled) |
| Strategy | `Heartbeat Test` |
| cadence_bars | `60` |
| offset_bars | `0` |
| atr_multiplier | `2.0` |
| rr_ratio | `2.0` |
| direction_mode | `alternate` |

> **Stops are ATR-scaled, not pip-based.** SL distance = current 14-period ATR × `atr_multiplier`. TP = SL × `rr_ratio`. This means the strategy works on any symbol without setting a pip size — the broker won't reject for "Invalid stops" (code 10016) on volatile instruments like XAUUSD.

Click **Launch Scanner**.

### 2.2 — Expected immediate behavior (within 3 seconds)

- [ ] **Success toast**: "Scanner 'Heartbeat EURUSD' started — N historical signals loaded" (N should be roughly 3000 / 60 ≈ 50, minus anything lost to warmup)
- [ ] **Button text returns to "Launch Scanner"** (no ⚡ emoji — C-9 check)
- [ ] **Left pane "Live Scanners" section appears** with a scanner card:
  - Card shows name "Heartbeat EURUSD"
  - LED is green pulsing (led-live)
  - Meta: "Heartbeat Test · EURUSD · M1"
  - Chip shows signal count (should be > 0 after backfill)
- [ ] **Dashboard → Active Instances** lists the scanner
- [ ] **Dashboard telemetry tiles** update: Active Scanners = 1
- [ ] **Footer stats text** updates: "Scanners 1 | Signals today N | Auto-trades 0" (C-10 check)
- [ ] **Click the scanner card** → main area shows a full panel with 4 stat tiles (Total/Longs/Shorts/Success Rate), a column header row, and signal rows populated from backfill

### 2.3 — Historical backfill signals verification

In the scanner panel, check the table:
- [ ] **Total tile** matches the number of rows displayed
- [ ] **Longs tile + Shorts tile = Total** (since alternate mode, should be roughly equal)
- [ ] **Each row shows**: direction badge, symbol, timeframe M1, price, SL, TP, status "RUNNING", time
- [ ] **BUY rows** have green badge; **SELL rows** have red badge
- [ ] **SL/TP** numeric for all rows (Heartbeat always sends both)
- [ ] Newest row is at top; oldest at bottom

### 2.4 — Charts panel integration

- [ ] **Click Charts** in left nav → add a chart: symbol EURUSD, timeframe M1, + Add Chart
- [ ] Chart renders with candles
- [ ] **Historical signals from Heartbeat appear as markers** on the chart (arrows up for BUY, down for SELL)
- [ ] Click the expand button (↗) on the chart → chart modal opens fullscreen
- [ ] Close modal (X or Esc) → returns to grid

### 2.5 — Live signal test (wait for a new one)

Note the current UTC time. Next BUY will fire at minute `M + (60 - (M mod 60))` where `M` is the current minute — i.e. at the top of the next hour, roughly, since cadence=60 means one signal per 60 M1 bars.

Wait up to 60 minutes, or reduce cadence to make this faster:

**Shortcut:** stop the Heartbeat scanner, relaunch with `cadence_bars: 5`. You'll then get a new signal every 5 minutes.

When a new signal fires:
- [ ] **Toast** appears top-right: "BUY · EURUSD [M1] @ <price>"
- [ ] **Toast shows single `✓` icon** (not doubled `✓ ✓` — C-9 check)
- [ ] **Scanner card signal chip** increments
- [ ] **Scanner panel table** shows the new row at top
- [ ] **Scanner panel Total tile** increments
- [ ] **Chart panel**: new arrow marker appears
- [ ] **Right-pane activity feed** prepends a new row within ~1 second:
  - Format: `HH:MM:SS · EURUSD signal · BUY` (with colored badge)

### 2.6 — Auto-trade live test (DEMO ACCOUNT ONLY)

**⚠️ Ensure you're on an MT5 demo account. Real money will be placed otherwise.**

On the Heartbeat scanner's Dashboard card (or Trading → Auto Mode), enable auto-trade:
- Toggle the AUTO switch
- Set volume: `0.01` (smallest lot)
- Confirm the "place REAL orders" modal

- [ ] **Auto-trade status badge** on card changes to green "AUTO"
- [ ] **Scanner card chips** now include `AUTO` chip
- [ ] **Footer stats text** updates: "Auto-trades 1"

Wait for the next signal:
- [ ] **Toast**: "Auto-placed: EURUSD ticket #NNNNN" (single `✓` — C-9)
- [ ] **Right-pane OPEN POSITIONS** count increments within 500ms (C-7 check)
- [ ] **Right-pane positions list** shows the new position as a compact row:
  - Symbol + BUY badge on left
  - PnL + current price on right
  - Grid layout (not unstyled — F-2 check)
- [ ] **Right-pane equity** may update (margin taken)
- [ ] **Position row** updates every refresh tick — current price, floating pnl color (green/red)

### 2.7 — Wait for SL or TP hit

Let the position run. When it hits SL or TP:
- [ ] **Scanner panel row status** changes from `RUNNING` to `TP HIT` (green) or `SL HIT` (red)
- [ ] **Within 500ms**: right-pane positions list drops the row (C-7 check)
- [ ] **Right-pane equity** reflects the close (profit or loss added to balance)
- [ ] **Header equity + PnL** both update
- [ ] **Activity feed** shows the close event

### 2.8 — Manual order test

Trading panel → Manual Order tab:
- Symbol: EURUSD
- Volume: 0.01
- Direction: BUY
- SL enabled: tick, set to market - 20 pips
- TP enabled: tick, set to market + 40 pips
- Click Place Order → confirm

- [ ] Success toast with ticket number
- [ ] **Right-pane positions** shows new row within ~500ms
- [ ] **Header equity** updates

### 2.9 — Close All test (F-6)

Right-pane → **Close All** button:
- [ ] Confirm modal appears
- [ ] On confirm: toast "Closed N positions" (NOT "Request failed" — F-6 check)
- [ ] Right-pane positions list empties
- [ ] Header equity reflects closes
- [ ] Footer errors counter stays at 0

### 2.10 — Stop scanner

Dashboard → Active Instances → **Stop** button on Heartbeat:
- Confirm modal
- [ ] Toast: "Scanner 'Heartbeat EURUSD' stopped"
- [ ] Scanner card disappears from left pane
- [ ] Scanner panel disappears from main area; switches to MTF Strategy panel
- [ ] Footer stats: "Scanners 0"

---

## Part 3 · Backtest verification (predictable count math)

**Goal:** verify backtest over a known window produces exactly the number of signals the strategy's cadence math predicts. Zero tolerance — if off by even 1, something's wrong.

### 3.1 — Setup

Strategies panel → set up Heartbeat identically to 2.1 **except**:
- cadence_bars: `100`
- offset_bars: `1440` (skip the backtest engine's 1440-bar warmup — backtest suppresses signals for the first 1440 bars regardless)

Don't launch live. Find the backtest button on the scanner panel (or wherever backtesting is triggered in your current UI — spec calls for a Backtest tab on the Strategies panel).

**If backtest UI is not visible**, that's a separate issue — note it and skip this part.

### 3.2 — Backtest math

Run a backtest over **3 full days** of EURUSD M1 data (4320 M1 bars).
After subtracting 1440 warmup: 2880 bars of "live" window.
Signals in alternate mode with C=100: BUYs at 0, 100, 200, ..., 2800 → 29 BUYs. SELLs at 50, 150, ..., 2850 → 29 SELLs. Total: 58.

- [ ] Backtest completes
- [ ] Signal count in result matches **58 ± 1** (the ±1 is for boundary handling)
- [ ] Each signal has consistent SL and TP values (Heartbeat always sets both)

If the count is wildly off (e.g. 0, or > 100), something is broken in either the backtester, the on_start call semantics, or the warmup handling.

---

## Part 4 · Edge stress — one mode at a time

**Goal:** exercise each failure mode. For each, launch a scanner with that mode, verify expected behavior, stop the scanner, move to next mode.

**Naming convention:** use session names like `Edge · crash_on_bar`, `Edge · rapid_fire`, etc. — makes left-pane navigation clear.

### 4.1 — Mode: `crash_on_bar` (fault handler, footer errors, SCANNER_ERROR)

Launch with: `mode=crash_on_bar`, `crash_every_n_bars=5`, `cadence_bars=50`.

After launch, within ~30 seconds you should see 5 consecutive `on_bar` exceptions. Expected:
- [ ] **Error toast**: "Scanner Error (<id>): ValueError: ..."
- [ ] **Footer errors counter** increments each time a fault reaches the WS path (C-11)
- [ ] After 5 consecutive faults: **Scanner card LED turns red** (led-error)
- [ ] Scanner no longer processes new bars (check engine.log for "HALTED")
- [ ] **Click the red errors count in footer** → resets to `errors 0` with muted color (C-11 reset)

### 4.2 — Mode: `crash_on_start`

Launch with: `mode=crash_on_start`.

- [ ] **Error toast** or error in top banner on page (dashboard.js wraps init in try/catch)
- [ ] Scanner MAY still register in the active list but emits no signals
- [ ] No UI lock-up — you can still navigate, launch other scanners, etc.
- [ ] Check `backend/logs/engine.log` — should contain "on_start failed: RuntimeError: crash_on_start mode"

### 4.3 — Mode: `bad_signal_string`

Launch with: `mode=bad_signal_string`, `cadence_bars=30`.

The parser raises `ValueError` on unknown direction strings. Because the
strategy returns the bad string only every 30 bars, faults are
NON-consecutive — scanner does not halt.

- [ ] Scanner runs, does NOT halt (no red LED, no scanner-card chip change)
- [ ] NO signals appear in the panel (parser raises before any signal can be emitted)
- [ ] Footer errors counter increments by 1 every ~30 bars (each parse exception emits SCANNER_ERROR)
- [ ] Toast: "Scanner Error (...): ValueError: ..." appears every fault
- [ ] Engine log shows `Strategy.on_bar() raised | ... ValueError: Strategy returned string 'MAYBE_BUY'`

### 4.4 — Mode: `bad_signal_tuple`

Launch with: `mode=bad_signal_tuple`. (`cadence_bars` is ignored — the
strategy returns the malformed tuple on every bar.)

The parser raises on the `float("not-a-number")` conversion. Because the
strategy fires on EVERY bar, faults are CONSECUTIVE — scanner halts after
MAX_BAR_FAULTS=5.

- [ ] Within ~25 seconds (5 polls × 5s) scanner enters HALT state
- [ ] Same SCANNER_ERROR toast / red LED / footer-errors increment as 4.1
- [ ] Engine log shows `Scanner HALTED after 5 consecutive bar faults`
- [ ] After halt: no more bar processing, no more error toasts (one final batch only)

### 4.5 — Mode: `rapid_fire` (dedup + throughput)

Launch with: `mode=rapid_fire`. **Do NOT enable auto-trade on this one.**

- [ ] Signals flood in — one per M1 bar. Panel table fills rapidly.
- [ ] **Right-pane activity feed** caps at 20 and rotates (oldest drops)
- [ ] **Footer signal counter** climbs fast
- [ ] Browser stays responsive (no lockup)
- [ ] Stop the scanner. Signals stop immediately.

---

> ### ⚠ pip_size warning — read before running 4.6 through 4.11
>
> Edge Stress Test uses pip-based stops with the `pip_size` config field.
> Default is `0.0001` (EURUSD-only). For other symbols set:
>
> - EURUSD, GBPUSD, USDJPY (4-digit pip): `pip_size = 0.0001`
> - XAUUSD, XAGUSD: `pip_size = 0.1`
> - BTCUSD: `pip_size = 1.0`
>
> Wrong `pip_size` will cause every auto-order to fail with broker code
> 10016 ("Invalid stops"). This is **not a platform bug** — it's strategy
> config. If you see AUTO_FAILED on every signal with "Invalid stops" in
> the error, check `pip_size` first before reporting a regression.
>
> Heartbeat Test does NOT have this issue because it uses ATR-scaled stops.

---

### 4.6 — Mode: `sl_only` + auto-trade

Launch with: `mode=sl_only`, `cadence_bars=50`. Enable auto-trade at 0.01 lots on demo.

- [ ] Auto-placed orders all have SL set, TP empty (check MT5 or scanner panel TP column = "—")
- [ ] No orders rejected by validator (SL-only is a valid order)

### 4.7 — Mode: `tp_only` + auto-trade

Launch with: `mode=tp_only`, `cadence_bars=50`. Enable auto-trade.

- [ ] Auto-placed orders have TP set, SL empty
- [ ] No validator rejections

### 4.8 — Mode: `no_sl_tp` + auto-trade

Launch: `mode=no_sl_tp`. Auto-trade on.

- [ ] Orders placed with no SL and no TP (raw market orders)
- [ ] No validator rejections

### 4.9 — Mode: `impossible_sl` + auto-trade

Launch: `mode=impossible_sl`, `cadence_bars=50`. Auto-trade **on**.

Every signal has an SL above entry for a BUY (inverted). The validator should reject every one:
- [ ] **Each signal**: "Auto-trade failed: EURUSD — <validator error>" toast (single `✗` — C-9)
- [ ] **Footer errors** increments each failure (C-11)
- [ ] **After 5 failures** (or whatever `MAX_AUTO_FAILS` is): scanner auto-trade DISABLES
- [ ] Scanner card chip changes from `AUTO` to `HALTED` (with red chip-warn styling)
- [ ] Re-enabling auto-trade requires manual toggle

### 4.10 — Mode: `flip_flop` + auto-trade (direction-flip logic)

Launch: `mode=flip_flop`, `cadence_bars=50`. Auto-trade on, 0.01 lots.

Every 50 bars alternates BUY → SELL → BUY. The auto-executor should close the prior opposite position before opening the new one:
- [ ] First signal opens BUY. Right-pane shows 1 BUY position.
- [ ] Second signal (SELL): BUY closes, new SELL opens. Right-pane shows 1 SELL position.
- [ ] Third signal (BUY): SELL closes, new BUY opens.
- [ ] **Position count stays at 1** for this scanner throughout (not accumulating)

### 4.11 — Mode: `same_signal_repeat` + auto-trade (signal ID dedup)

Launch: `mode=same_signal_repeat`, `cadence_bars=20`. Auto-trade on.

Every 20 bars, fires BUY. Auto-executor should NOT place a new order if a matching-tag position already exists:
- [ ] First signal: BUY opens. 1 position.
- [ ] Next signal (still BUY, different signal_id): auto-executor ignores it because `len(owned) >= max_open_positions` (default 1). It dedupes by position count limit, not by signal tag.
- [ ] Document observed behavior. If you see positions accumulating forever, the dedup rule needs tightening.

### 4.12 — Mode: `state_accumulator` (P0-A: on_start/on_update split)

**This is the critical regression test for the P0-A fix.** If this passes, the old "on_start called every poll, wiping state" bug is confirmed dead.

Launch: `mode=state_accumulator`, `state_threshold=5`, `cadence_bars=30`.

After launch:
- [ ] **Zero signals appear for the first few minutes** — the internal `state.update_count` is still under 5.
- [ ] **After 5 live polls** (each poll ~5 seconds = 25-30s real time), `state.update_count` reaches 5
- [ ] **Then** the scanner starts firing BUY every 30 bars
- [ ] If signals appeared IMMEDIATELY at launch, `on_start` is being re-called per poll and wiping state — P0-A regression

**Cross-check (intentional null result).** Run the same mode in backtest. The
backtest engine calls `on_start` and `on_bar` only — never `on_update`. So
`state["update_count"]` stays at 0 throughout the backtest, the threshold is
never crossed, and the backtest produces ZERO signals. This is by design.

If you see signals in backtest, something is calling `on_update` during
backtest that shouldn't be — that would itself be a regression. Zero signals
in backtest + signals after threshold in live is the passing condition.

### 4.13 — Mode: `slow_on_bar`

Launch: `mode=slow_on_bar`, `slow_sleep_ms=200`, `cadence_bars=50`.

Each on_bar takes 200ms. At M1 polling every 5s, processing a new bar takes negligible extra time, but the backfill scan of 3000 bars takes 600 seconds. So:
- [ ] Initial launch may take a LONG time to complete historical backfill (600+ seconds)
- [ ] During backfill: UI shows "Starting..." button state. Launch button stays disabled.
- [ ] Eventually scanner appears. Live works fine afterward.
- [ ] No timeout errors from the backend (unless you have a request timeout tighter than 10 min)

If backfill times out, the engine needs a longer request timeout for historical scan — note and report.

### 4.14 — Mode: `warmup_check`

Launch: `mode=warmup_check`.

This mode returns BUY on bar index 0 only. The engine should silently absorb this (warmup = first 1440 bars):
- [ ] **Historical backfill**: 0 signals loaded (toast says "0 historical signals")
- [ ] **Scanner panel**: empty state "Waiting for signals…"
- [ ] No signal ever fires for this scanner

If a BUY signal appears at bar 0, warmup suppression is broken — note and report.

### 4.15 — Multiple scanners stopping test (C-14 fix)

With at least 3 edge-mode scanners still running from earlier tests:
- [ ] Stop one of them (not the last)
- [ ] **Other scanner cards remain visible in left pane** (C-14 check)
- [ ] Stop all but one
- [ ] Last scanner card still visible, "Live Scanners" section header still shown
- [ ] Stop the last
- [ ] "Live Scanners" section HIDES

---

## Part 5 · Risk guard test

Trading panel → Risk Guard:

- [ ] Enable Risk Threshold, set to 2%, enable Auto-close on breach → Update Risk Guard
- [ ] Toast: "Risk guard updated"
- [ ] **Header risk chip** changes from DISARMED to `RISK: 2.0%` in warning color (C-13 check)

With open positions, force a drawdown (use auto-trade on `impossible_sl` or manually place losing trades):
- [ ] When floating PnL drops past 2% of equity: **all positions close automatically**
- [ ] Toast appears: "Risk breach — positions closed" (or similar)
- [ ] Footer errors may increment

Disable risk guard → Update:
- [ ] Header chip returns to `DISARMED` (muted)

---

## Part 6 · Orphan detection test (P1-E)

This needs a simulated crash-recovery scenario:

1. Launch Heartbeat, enable auto-trade, let it open 1-2 positions.
2. **While positions are open**, kill the backend server (Ctrl+C on `start.bat` terminal, or close the window).
3. Restart the server.
4. Open the browser app fresh.

On boot:
- [ ] Backend reconcile runs — check `backend/logs/engine.log` for "Orphan positions detected: N"
- [ ] On page load, orphan detection modal appears: "Orphan Positions Detected — N orphan auto-trade positions found..."
- [ ] Clicking confirm clears the orphan tracking
- [ ] Orphan positions are NOT re-adopted as scanner positions — they're surfaced for manual close
- [ ] Modal title is plain "Orphan Positions Detected" (no ⚠️ emoji — C-9 check)

---

## Part 7 · Strategy deletion

Create Strategy panel → Uploaded Strategies list:
- [ ] Both test strategies appear
- [ ] Click delete on `test_edge_stress_strategy.py`
- [ ] Confirm
- [ ] Strategy disappears from list AND from Strategies dropdown
- [ ] Any running Edge scanners continue to function (backend keeps the module loaded)
- [ ] New Edge scanners can no longer be launched

Re-upload to restore for further testing.

---

## Part 8 · Summary — what this runbook has proven when all checks pass

**UI shell integrity** — header widgets wired to real data; footer reflects live state; kill-switch honest; command palette routes correctly; right pane renders and refreshes.

**Strategy → engine contract** — on_start called once; on_update called per poll with state persistence (no wipe); on_bar exceptions caught, counted, halted after 5; unknown signal formats handled; structured Signal dataclass round-trips end-to-end.

**Signal flow** — historical backfill populates panels; live signals flow via WebSocket; dedup by signal ID prevents duplicates; chart markers drawn; activity feed rotates; toast notifications deliver.

**Order path** — manual orders work; auto-trade opens real orders; validator rejects bad SL/TP; auto-executor dedupes by position tag; direction-flip closes prior opposite; SL/TP hits update status; right pane refreshes within 500ms of trade events (C-7).

**Accounting** — equity, balance, margin, floating all update on 10s poll AND on trade events; sparkline renders; header PnL colors correctly.

**Scanner lifecycle** — launch creates card + panel; multiple scanners coexist; stopping one doesn't affect others (C-14); stopping last hides the Live Scanners section; process restart orphan detection works.

**Safety** — risk guard trips auto-close; kill-switch blocks auto-trades while ON; strategy fault halts the individual scanner without affecting others.

If all Part 1-7 checks pass, the v2.4 platform is verified.

---

## Part 9 · If something fails

When a check fails, record:
1. Which check ID (e.g. "2.5 live signal toast")
2. What happened instead of expected
3. Relevant log tail — `backend/logs/engine.log`, `backend/logs/app.log`, `backend/logs/order.log`, `backend/logs/errors.log`
4. Browser console errors (F12 → Console)

Report back as a single message. Don't try to patch during the run — finish the run, aggregate findings, then patch.

---

## Appendix A · Known caveats

- **The C-7 status list in my earlier fix guide had wrong strings.** Backend actually emits `"TP HIT"` and `"SL HIT"` with spaces, not `TP_HIT`/`SL_HIT`, and there is no generic `CLOSED` status. If the MT5_MUTATING array in dashboard.js uses the underscored form, positions will NOT refresh on SL/TP hits. **Check line 1147 of dashboard.js.** If it's `['AUTO_PLACED', 'CLOSED', 'SL_HIT', 'TP_HIT']`, change to `['AUTO_PLACED', 'SL HIT', 'TP HIT']`. This is the only known correctness issue carried over from the fix guide.

- **Warmup window differs for live vs backtest.** In backtest, the engine skips the first 1440 M1 bars (1 day) by default. For the live scanner historical backfill, the engine scans the last 2880 bars (if 3000 are fetched, it skips the first ~120; zero skipped if <2880). Any strategy configured to fire early in the skipped window will have those signals silently suppressed. Backfill signal counts will be lower than naive cadence math predicts.

- **MT5 demo vs live.** All auto-trade tests in Part 4 assume a demo account. Do not run 4.5 (rapid_fire), 4.9 (impossible_sl), or 4.11 (same_signal_repeat) on a live account.

- **Poll interval is 5 seconds.** Most "within 500ms" assertions assume the WebSocket push path is active. If a check fails but resolves after ~10 seconds, the WebSocket path is broken and the 10s HTTP poll is masking it.

- **This runbook does not test TradingView integration, binance-crypto path, or the Charts panel's WebSocket stream** beyond basic rendering. Those are platform-level integration tests, not strategy tests.
