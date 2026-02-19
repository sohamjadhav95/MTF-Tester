"""
Core Backtesting Engine
Bar-by-bar backtester with no look-ahead bias.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from .models import Trade, Position, BacktestConfig, BacktestResult


class Backtester:
    """
    Bar-by-bar backtesting engine.
    
    Processes bars sequentially, calling strategy.on_bar() on each bar
    with only data available up to that point (no look-ahead bias).
    Handles position management, PnL calculation, and equity tracking.
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.balance = config.initial_balance
        self.equity = config.initial_balance
        self.position: Position | None = None
        self.trades: list[Trade] = []
        self.equity_curve: list[dict] = []
        self.peak_equity = config.initial_balance

    def run(self, data: pd.DataFrame, strategy) -> BacktestResult:
        """
        Run the backtest.
        
        Args:
            data: DataFrame with columns [time, open, high, low, close, volume, spread]
            strategy: Instance of a BaseStrategy subclass (with on_bar method)
        
        Returns:
            BacktestResult with trades, equity curve, and metrics
        """
        if data.empty:
            raise ValueError("Cannot run backtest on empty data")

        total_bars = len(data)

        for i in range(total_bars):
            # Get data up to and including current bar (no look-ahead)
            current_data = data.iloc[: i + 1].copy()
            current_bar = data.iloc[i]
            current_time = current_bar["time"]

            # Get signal from strategy
            signal = strategy.on_bar(i, current_data)

            # Get spread for this bar
            spread_points = self._get_spread(current_bar)

            # Process signal
            self._process_signal(signal, current_bar, spread_points, i)

            # Calculate current equity (including unrealized PnL)
            unrealized_pnl = 0.0
            if self.position is not None:
                unrealized_pnl = self._calculate_unrealized_pnl(
                    current_bar, spread_points
                )

            self.equity = self.balance + unrealized_pnl

            # Track peak equity and drawdown
            if self.equity > self.peak_equity:
                self.peak_equity = self.equity

            drawdown_pct = 0.0
            if self.peak_equity > 0:
                drawdown_pct = (
                    (self.peak_equity - self.equity) / self.peak_equity
                ) * 100

            self.equity_curve.append({
                "time": current_time.isoformat() if isinstance(current_time, datetime) else str(current_time),
                "equity": round(self.equity, 2),
                "balance": round(self.balance, 2),
                "drawdown_pct": round(drawdown_pct, 4),
            })

        # Close any remaining position at the last bar
        if self.position is not None:
            last_bar = data.iloc[-1]
            spread_points = self._get_spread(last_bar)
            self._close_position(last_bar, spread_points, len(data) - 1)

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
            bar_data.append({
                "time": row["time"].isoformat() if isinstance(row["time"], datetime) else str(row["time"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]) if pd.notna(row["volume"]) else 0,
            })

        # Calculate metrics
        from analytics.metrics import calculate_metrics
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

    def _get_spread(self, bar: pd.Series) -> int:
        """Get spread in points for the current bar."""
        if self.config.use_spread_from_data:
            return int(bar.get("spread", 0))
        return self.config.fixed_spread_points

    def _process_signal(
        self,
        signal: str,
        bar: pd.Series,
        spread_points: int,
        bar_index: int,
    ):
        """Process a signal from the strategy."""
        signal = signal.upper() if isinstance(signal, str) else "HOLD"

        if signal not in ("BUY", "SELL", "HOLD"):
            return  # Invalid signal, do nothing

        if signal == "HOLD":
            return

        # If we have a position in the opposite direction, close it first
        if self.position is not None:
            if self.position.direction != signal:
                # Close existing position
                self._close_position(bar, spread_points, bar_index)
                # Open new position in the signal direction
                self._open_position(signal, bar, spread_points, bar_index)
            # If same direction, hold (already in position)
        else:
            # No position, open one
            self._open_position(signal, bar, spread_points, bar_index)

    def _open_position(
        self,
        direction: str,
        bar: pd.Series,
        spread_points: int,
        bar_index: int,
    ):
        """Open a new position."""
        close_price = float(bar["close"])
        spread_value = spread_points * self.config.point

        if direction == "BUY":
            # Buy at ask (close + spread)
            entry_price = close_price + spread_value
        else:
            # Sell at bid (close price)
            entry_price = close_price

        self.position = Position(
            direction=direction,
            entry_price=entry_price,
            entry_time=bar["time"],
            lot_size=self.config.lot_size,
            entry_bar_index=bar_index,
        )

    def _close_position(
        self,
        bar: pd.Series,
        spread_points: int,
        bar_index: int,
    ):
        """Close the current position and record the trade."""
        if self.position is None:
            return

        close_price = float(bar["close"])
        spread_value = spread_points * self.config.point

        if self.position.direction == "BUY":
            # Close long: sell at bid (close price)
            exit_price = close_price
        else:
            # Close short: buy at ask (close + spread)
            exit_price = close_price + spread_value

        # Calculate PnL in pips (1 pip = 10 points for 5-digit, 1 point for less)
        pip_size = self.config.point * 10 if self.config.digits == 5 or self.config.digits == 3 else self.config.point

        if self.position.direction == "BUY":
            pnl_price_diff = exit_price - self.position.entry_price
        else:
            pnl_price_diff = self.position.entry_price - exit_price

        pnl_pips = pnl_price_diff / pip_size

        # Calculate PnL in money
        # PnL = price_diff * contract_size * lots
        # For forex: tick_value gives us the value of one point movement
        pnl_money = (
            pnl_price_diff
            * self.config.contract_size
            * self.position.lot_size
        )

        # Apply commission (both sides)
        commission = self.config.commission_per_lot * self.position.lot_size * 2
        pnl_money -= commission

        # Spread cost in pips for reporting
        spread_cost_pips = spread_points * self.config.point / pip_size

        # Update balance
        self.balance += pnl_money

        # Bars held
        bars_held = bar_index - self.position.entry_bar_index

        # Record trade
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
        )
        self.trades.append(trade)

        # Clear position
        self.position = None

    def _calculate_unrealized_pnl(
        self, bar: pd.Series, spread_points: int
    ) -> float:
        """Calculate unrealized PnL for the current open position."""
        if self.position is None:
            return 0.0

        close_price = float(bar["close"])
        spread_value = spread_points * self.config.point

        if self.position.direction == "BUY":
            # If we closed now, we'd sell at bid (close)
            current_exit = close_price
            pnl_price_diff = current_exit - self.position.entry_price
        else:
            # If we closed now, we'd buy at ask (close + spread)
            current_exit = close_price + spread_value
            pnl_price_diff = self.position.entry_price - current_exit

        pnl_money = (
            pnl_price_diff
            * self.config.contract_size
            * self.position.lot_size
        )

        return pnl_money
