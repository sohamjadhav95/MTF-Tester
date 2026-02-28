"""
Core Backtesting Engine
=======================
Strategy-agnostic, bar-by-bar backtester.
Accepts any BaseStrategy instance — never imports specific strategies.

Supports:
  - SL/TP via per-bar high/low checks
  - Optional RiskManager for dynamic position sizing
  - Strategy lifecycle hooks: on_start(), on_finish()
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, Tuple, TYPE_CHECKING

from app.core.models import Trade, Position, BacktestConfig, BacktestResult
from app.core.risk import RiskManager

if TYPE_CHECKING:
    from app.core.strategy_template import BaseStrategy


class Backtester:
    """
    Bar-by-bar backtesting engine.

    Processes bars sequentially, calling strategy.on_bar() on each bar
    with only data available up to that point (no look-ahead bias).
    Handles position management, SL/TP checks, PnL calculation, and equity tracking.

    strategy.on_bar() may return either:
      - A plain string: "BUY" | "SELL" | "HOLD"
      - A tuple: ("BUY", sl_price, tp_price)  — sl/tp are floats or None
    """

    def __init__(
        self,
        config: BacktestConfig,
        risk_manager: Optional[RiskManager] = None,
    ):
        self.config = config
        self.risk_manager = risk_manager
        self.balance = config.initial_balance
        self.equity = config.initial_balance
        self.position: Optional[Position] = None
        self.trades: list[Trade] = []
        self.equity_curve: list[dict] = []
        self.peak_equity = config.initial_balance

    def run(self, data: pd.DataFrame, strategy: BaseStrategy, progress_callback=None) -> BacktestResult:
        """Run the backtest."""
        if data.empty:
            raise ValueError("Cannot run backtest on empty data")

        # ── Lifecycle: on_start ─────────────────────────────────
        if hasattr(strategy, "on_start"):
            strategy.on_start(data)

        total_bars = len(data)

        for i in range(total_bars):
            current_data = data.iloc[: i + 1].copy()
            current_bar = data.iloc[i]

            # ── 1. Check SL/TP on current bar BEFORE strategy signal ──
            if self.position is not None:
                sl_tp_result = self._check_sl_tp(current_bar)
                if sl_tp_result:
                    self._close_position_reason(
                        current_bar, self._get_spread(current_bar), i, sl_tp_result
                    )

            # ── 2. Get signal from strategy ──────────────────────
            raw = strategy.on_bar(i, current_data)

            signal, sl_price, tp_price = self._parse_signal(raw)
            spread_points = self._get_spread(current_bar)
            self._process_signal(signal, current_bar, spread_points, i, sl_price, tp_price)

            # ── 3. Track equity ──────────────────────────────────
            unrealized = 0.0
            if self.position is not None:
                unrealized = self._calculate_unrealized_pnl(current_bar, spread_points)
            self.equity = self.balance + unrealized

            if self.equity > self.peak_equity:
                self.peak_equity = self.equity

            drawdown_pct = 0.0
            if self.peak_equity > 0:
                drawdown_pct = ((self.peak_equity - self.equity) / self.peak_equity) * 100

            ts = current_bar["time"]
            if isinstance(ts, datetime):
                ts = ts.replace(tzinfo=None)
                ts_str = ts.isoformat()
            else:
                ts_str = str(ts)
            self.equity_curve.append({
                "time": ts_str,
                "equity": round(self.equity, 2),
                "balance": round(self.balance, 2),
                "drawdown_pct": round(drawdown_pct, 4),
            })
            
            if progress_callback and i % 500 == 0:
                progress_callback(i, total_bars)

        if progress_callback:
            progress_callback(total_bars, total_bars, "Finalizing metrics...")

        # Close any remaining position at the last bar
        if self.position is not None:
            last_bar = data.iloc[-1]
            self._close_position_reason(
                last_bar, self._get_spread(last_bar), len(data) - 1, "end"
            )

        # ── Lifecycle: on_finish ────────────────────────────────
        if hasattr(strategy, "on_finish"):
            strategy.on_finish(data)

        # Get indicator data from strategy for chart overlay
        indicator_data = {}
        if hasattr(strategy, "get_indicator_data"):
            try:
                indicator_data = strategy.get_indicator_data(data)
            except Exception:
                indicator_data = {}

        # Convert bar data for frontend
        bar_data = []
        for _, row in data.iterrows():
            t = row["time"]
            if isinstance(t, datetime):
                t = t.replace(tzinfo=None)
                t_str = t.isoformat()
            else:
                t_str = str(t)
            bar_data.append({
                "time": t_str,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]) if pd.notna(row["volume"]) else 0,
            })

        # Calculate metrics
        from app.analytics.metrics import calculate_metrics

        metrics = calculate_metrics(
            trades=self.trades,
            equity_curve=self.equity_curve,
            initial_balance=self.config.initial_balance,
            timeframe=self.config.timeframe,
        )

        return BacktestResult(
            config=self.config,
            trades=self.trades,
            equity_curve=self.equity_curve,
            metrics=metrics,
            indicator_data=indicator_data,
            bar_data=bar_data,
        )

    # ─── Signal Parsing ─────────────────────────────────────────
    def _parse_signal(self, raw) -> Tuple[str, Optional[float], Optional[float]]:
        """Parse strategy return value — string or (signal, sl, tp) tuple."""
        if isinstance(raw, tuple):
            signal = str(raw[0]).upper() if raw else "HOLD"
            sl = float(raw[1]) if len(raw) > 1 and raw[1] is not None else None
            tp = float(raw[2]) if len(raw) > 2 and raw[2] is not None else None
            return signal, sl, tp
        signal = str(raw).upper() if raw else "HOLD"
        return signal, None, None

    # ─── SL / TP Check ──────────────────────────────────────────
    def _check_sl_tp(self, bar: pd.Series) -> Optional[str]:
        """
        Check if the current bar's high/low triggered SL or TP.
        TP is checked first (optimistic — assume TP hit before SL on same bar).
        Returns 'tp', 'sl', or None.
        """
        pos = self.position
        if pos is None:
            return None

        high = float(bar["high"])
        low = float(bar["low"])

        if pos.direction == "BUY":
            if pos.tp_price is not None and high >= pos.tp_price:
                return "tp"
            if pos.sl_price is not None and low <= pos.sl_price:
                return "sl"
        else:
            if pos.tp_price is not None and low <= pos.tp_price:
                return "tp"
            if pos.sl_price is not None and high >= pos.sl_price:
                return "sl"

        return None

    # ─── Position Lifecycle ─────────────────────────────────────
    def _get_spread(self, bar: pd.Series) -> int:
        if self.config.use_spread_from_data:
            return int(bar.get("spread", 0))
        return self.config.fixed_spread_points

    def _process_signal(
        self,
        signal: str,
        bar: pd.Series,
        spread_points: int,
        bar_index: int,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
    ):
        if signal not in ("BUY", "SELL"):
            return

        if self.position is not None:
            if self.position.direction != signal:
                self._close_position_reason(bar, spread_points, bar_index, "signal")
                self._open_position(signal, bar, spread_points, bar_index, sl_price, tp_price)
        else:
            self._open_position(signal, bar, spread_points, bar_index, sl_price, tp_price)

    def _get_lot_size(self, sl_price: Optional[float], entry_price: float) -> float:
        """Determine lot size — use risk manager if available, else config."""
        if self.risk_manager is not None and sl_price is not None:
            sl_distance = abs(entry_price - sl_price)
            if sl_distance > 0:
                return self.risk_manager.calculate_position_size(
                    balance=self.balance,
                    sl_distance=sl_distance,
                    contract_size=self.config.contract_size,
                    point=self.config.point,
                )
        return self.config.lot_size

    def _open_position(
        self,
        direction: str,
        bar: pd.Series,
        spread_points: int,
        bar_index: int,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
    ):
        close_price = float(bar["close"])
        spread_value = spread_points * self.config.point

        if direction == "BUY":
            entry_price = close_price + spread_value
        else:
            entry_price = close_price

        lot_size = self._get_lot_size(sl_price, entry_price)

        self.position = Position(
            direction=direction,
            entry_price=entry_price,
            entry_time=bar["time"],
            lot_size=lot_size,
            entry_bar_index=bar_index,
            sl_price=sl_price,
            tp_price=tp_price,
        )

    def _close_position_reason(
        self,
        bar: pd.Series,
        spread_points: int,
        bar_index: int,
        reason: str,
    ):
        """Close position with a specific exit reason (signal / sl / tp / end)."""
        if self.position is None:
            return

        close_price = float(bar["close"])
        spread_value = spread_points * self.config.point

        # Determine exit price based on reason
        if reason == "tp" and self.position.tp_price is not None:
            exit_price = self.position.tp_price
        elif reason == "sl" and self.position.sl_price is not None:
            exit_price = self.position.sl_price
        else:
            # Signal flip or end of test — exit at market (close price)
            if self.position.direction == "BUY":
                exit_price = close_price
            else:
                exit_price = close_price + spread_value

        # pip size
        pip_size = (
            self.config.point * 10
            if self.config.digits in (5, 3)
            else self.config.point
        )

        if self.position.direction == "BUY":
            pnl_price_diff = exit_price - self.position.entry_price
        else:
            pnl_price_diff = self.position.entry_price - exit_price

        pnl_pips = pnl_price_diff / pip_size
        pnl_money = pnl_price_diff * self.config.contract_size * self.position.lot_size

        commission = self.config.commission_per_lot * self.position.lot_size * 2
        pnl_money -= commission

        spread_cost_pips = spread_points * self.config.point / pip_size
        self.balance += pnl_money
        bars_held = bar_index - self.position.entry_bar_index

        trade = Trade(
            entry_time=self.position.entry_time,
            exit_time=bar["time"],
            direction=self.position.direction,
            entry_price=round(self.position.entry_price, self.config.digits),
            exit_price=round(exit_price, self.config.digits),
            lot_size=self.position.lot_size,
            pnl_pips=round(pnl_pips, 2),
            pnl_money=round(pnl_money, 2),
            spread_cost_pips=round(spread_cost_pips, 2),
            bars_held=bars_held,
            sl_price=self.position.sl_price,
            tp_price=self.position.tp_price,
            exit_reason=reason,
        )
        self.trades.append(trade)
        self.position = None

    def _calculate_unrealized_pnl(self, bar: pd.Series, spread_points: int) -> float:
        if self.position is None:
            return 0.0

        close_price = float(bar["close"])
        spread_value = spread_points * self.config.point

        if self.position.direction == "BUY":
            pnl_price_diff = close_price - self.position.entry_price
        else:
            pnl_price_diff = self.position.entry_price - (close_price + spread_value)

        return pnl_price_diff * self.config.contract_size * self.position.lot_size
