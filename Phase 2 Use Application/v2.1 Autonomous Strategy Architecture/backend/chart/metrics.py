"""
Analytics / Metrics Module
Calculates comprehensive performance metrics from backtest results.
"""

import math
import numpy as np
from main.config import BARS_PER_YEAR


def calculate_metrics(
    trades: list,
    equity_curve: list[dict],
    initial_balance: float,
    timeframe: str,
) -> dict:
    """
    Calculate comprehensive performance metrics.
    
    Args:
        trades: List of Trade objects
        equity_curve: List of {time, equity, balance, drawdown_pct} dicts
        initial_balance: Starting balance
        timeframe: Timeframe string for annualization
    
    Returns:
        Dict of metric name -> value
    """
    metrics = {}

    total_trades = len(trades)
    metrics["total_trades"] = total_trades

    if total_trades == 0:
        metrics.update({
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "net_pnl_pips": 0.0,
            "net_pnl_money": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "avg_win_pips": 0.0,
            "avg_loss_pips": 0.0,
            "avg_win_money": 0.0,
            "avg_loss_money": 0.0,
            "largest_win_pips": 0.0,
            "largest_loss_pips": 0.0,
            "largest_win_money": 0.0,
            "largest_loss_money": 0.0,
            "avg_trade_pnl_pips": 0.0,
            "avg_trade_pnl_money": 0.0,
            "avg_bars_held": 0.0,
            "max_drawdown_pct": 0.0,
            "max_drawdown_money": 0.0,
            "sharpe_ratio": 0.0,
            "recovery_factor": 0.0,
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
            "final_balance": initial_balance,
            "total_return_pct": 0.0,
            "total_spread_cost_pips": 0.0,
        })
        return metrics

    # Separate winners and losers
    winners = [t for t in trades if t.pnl_pips > 0]
    losers = [t for t in trades if t.pnl_pips <= 0]
    breakeven = [t for t in trades if t.pnl_pips == 0]

    winning_count = len(winners)
    losing_count = len(losers)

    metrics["winning_trades"] = winning_count
    metrics["losing_trades"] = losing_count
    metrics["win_rate"] = round((winning_count / total_trades) * 100, 2)

    # PnL calculations
    gross_profit = sum(t.pnl_money for t in winners)
    gross_loss = abs(sum(t.pnl_money for t in losers))

    metrics["gross_profit"] = round(gross_profit, 2)
    metrics["gross_loss"] = round(gross_loss, 2)

    # Profit factor
    if gross_loss > 0:
        metrics["profit_factor"] = round(gross_profit / gross_loss, 2)
    else:
        metrics["profit_factor"] = float("inf") if gross_profit > 0 else 0.0

    # Net PnL
    net_pnl_pips = sum(t.pnl_pips for t in trades)
    net_pnl_money = sum(t.pnl_money for t in trades)
    metrics["net_pnl_pips"] = round(net_pnl_pips, 2)
    metrics["net_pnl_money"] = round(net_pnl_money, 2)

    # Average win/loss
    if winning_count > 0:
        metrics["avg_win_pips"] = round(
            sum(t.pnl_pips for t in winners) / winning_count, 2
        )
        metrics["avg_win_money"] = round(gross_profit / winning_count, 2)
    else:
        metrics["avg_win_pips"] = 0.0
        metrics["avg_win_money"] = 0.0

    if losing_count > 0:
        metrics["avg_loss_pips"] = round(
            sum(t.pnl_pips for t in losers) / losing_count, 2
        )
        metrics["avg_loss_money"] = round(
            sum(t.pnl_money for t in losers) / losing_count, 2
        )
    else:
        metrics["avg_loss_pips"] = 0.0
        metrics["avg_loss_money"] = 0.0

    # Average trade
    metrics["avg_trade_pnl_pips"] = round(net_pnl_pips / total_trades, 2)
    metrics["avg_trade_pnl_money"] = round(net_pnl_money / total_trades, 2)

    # Largest win/loss
    all_pnl_pips = [t.pnl_pips for t in trades]
    all_pnl_money = [t.pnl_money for t in trades]

    metrics["largest_win_pips"] = round(max(all_pnl_pips), 2)
    metrics["largest_loss_pips"] = round(min(all_pnl_pips), 2)
    metrics["largest_win_money"] = round(max(all_pnl_money), 2)
    metrics["largest_loss_money"] = round(min(all_pnl_money), 2)

    # Average bars held
    avg_bars = sum(t.bars_held for t in trades) / total_trades
    metrics["avg_bars_held"] = round(avg_bars, 1)

    # Total spread cost
    total_spread = sum(t.spread_cost_pips for t in trades)
    metrics["total_spread_cost_pips"] = round(total_spread, 2)

    # Drawdown from equity curve
    max_dd_pct = 0.0
    max_dd_money = 0.0
    peak_equity = initial_balance

    for point in equity_curve:
        eq = point["equity"]
        if eq > peak_equity:
            peak_equity = eq
        dd_money = peak_equity - eq
        dd_pct = (dd_money / peak_equity) * 100 if peak_equity > 0 else 0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
        if dd_money > max_dd_money:
            max_dd_money = dd_money

    metrics["max_drawdown_pct"] = round(max_dd_pct, 2)
    metrics["max_drawdown_money"] = round(max_dd_money, 2)

    # Final balance and return
    final_balance = initial_balance + net_pnl_money
    metrics["final_balance"] = round(final_balance, 2)
    metrics["total_return_pct"] = round(
        ((final_balance - initial_balance) / initial_balance) * 100, 2
    )

    # Recovery factor
    if max_dd_money > 0:
        metrics["recovery_factor"] = round(
            net_pnl_money / max_dd_money, 2
        )
    else:
        metrics["recovery_factor"] = 0.0

    # Sharpe ratio (annualized)
    if len(equity_curve) > 1:
        equity_values = [p["equity"] for p in equity_curve]
        returns = []
        for j in range(1, len(equity_values)):
            if equity_values[j - 1] != 0:
                ret = (equity_values[j] - equity_values[j - 1]) / equity_values[j - 1]
                returns.append(ret)

        if len(returns) > 1:
            avg_return = np.mean(returns)
            std_return = np.std(returns, ddof=1)
            bars_year = BARS_PER_YEAR.get(timeframe, 252)

            if std_return > 0:
                metrics["sharpe_ratio"] = round(
                    (avg_return / std_return) * math.sqrt(bars_year), 2
                )
            else:
                metrics["sharpe_ratio"] = 0.0
        else:
            metrics["sharpe_ratio"] = 0.0
    else:
        metrics["sharpe_ratio"] = 0.0

    # Consecutive wins/losses
    max_consec_wins = 0
    max_consec_losses = 0
    current_streak = 0
    current_type = None  # "W" or "L"

    for t in trades:
        if t.pnl_pips > 0:
            if current_type == "W":
                current_streak += 1
            else:
                current_streak = 1
                current_type = "W"
            max_consec_wins = max(max_consec_wins, current_streak)
        else:
            if current_type == "L":
                current_streak += 1
            else:
                current_streak = 1
                current_type = "L"
            max_consec_losses = max(max_consec_losses, current_streak)

    metrics["max_consecutive_wins"] = max_consec_wins
    metrics["max_consecutive_losses"] = max_consec_losses

    return metrics
