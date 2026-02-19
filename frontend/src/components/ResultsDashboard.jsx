import './ResultsDashboard.css'

export default function ResultsDashboard({ results }) {
    if (!results) return null

    const { metrics, config } = results

    const metricCards = [
        { label: 'Net P&L', value: `$${metrics.net_pnl_money?.toLocaleString()}`, sub: `${metrics.net_pnl_pips} pips`, positive: metrics.net_pnl_money >= 0 },
        { label: 'Total Return', value: `${metrics.total_return_pct}%`, positive: metrics.total_return_pct >= 0 },
        { label: 'Total Trades', value: metrics.total_trades },
        { label: 'Win Rate', value: `${metrics.win_rate}%`, positive: metrics.win_rate >= 50 },
        { label: 'Profit Factor', value: metrics.profit_factor === Infinity ? '∞' : metrics.profit_factor, positive: metrics.profit_factor > 1 },
        { label: 'Max Drawdown', value: `${metrics.max_drawdown_pct}%`, sub: `$${metrics.max_drawdown_money?.toLocaleString()}`, negative: true },
        { label: 'Sharpe Ratio', value: metrics.sharpe_ratio, positive: metrics.sharpe_ratio > 0 },
        { label: 'Recovery Factor', value: metrics.recovery_factor },
        { label: 'Gross Profit', value: `$${metrics.gross_profit?.toLocaleString()}`, positive: true },
        { label: 'Gross Loss', value: `$${metrics.gross_loss?.toLocaleString()}`, negative: true },
        { label: 'Avg Win', value: `${metrics.avg_win_pips} pips`, sub: `$${metrics.avg_win_money}`, positive: true },
        { label: 'Avg Loss', value: `${metrics.avg_loss_pips} pips`, sub: `$${metrics.avg_loss_money}`, negative: true },
        { label: 'Largest Win', value: `${metrics.largest_win_pips} pips`, sub: `$${metrics.largest_win_money}`, positive: true },
        { label: 'Largest Loss', value: `${metrics.largest_loss_pips} pips`, sub: `$${metrics.largest_loss_money}`, negative: true },
        { label: 'Winning Trades', value: metrics.winning_trades, positive: true },
        { label: 'Losing Trades', value: metrics.losing_trades, negative: true },
        { label: 'Consec. Wins', value: metrics.max_consecutive_wins },
        { label: 'Consec. Losses', value: metrics.max_consecutive_losses },
        { label: 'Avg Bars Held', value: metrics.avg_bars_held },
        { label: 'Spread Cost', value: `${metrics.total_spread_cost_pips} pips` },
        { label: 'Final Balance', value: `$${metrics.final_balance?.toLocaleString()}`, positive: metrics.final_balance > (config?.initial_balance || 10000) },
    ]

    return (
        <div className="results-dashboard">
            <div className="results-header">
                <h2 className="results-title">Backtest Results</h2>
                <div className="results-meta">
                    <span className="meta-tag">{config?.symbol}</span>
                    <span className="meta-tag">{config?.timeframe}</span>
                    <span className="meta-tag">{config?.strategy}</span>
                    <span className="meta-tag">{results.total_bars} bars</span>
                </div>
            </div>

            {/* Main PnL Hero */}
            <div className={`pnl-hero ${metrics.net_pnl_money >= 0 ? 'profit' : 'loss'}`}>
                <div className="pnl-label">Net Profit / Loss</div>
                <div className="pnl-value">
                    {metrics.net_pnl_money >= 0 ? '+' : ''}${metrics.net_pnl_money?.toLocaleString()}
                </div>
                <div className="pnl-sub">
                    {metrics.net_pnl_pips >= 0 ? '+' : ''}{metrics.net_pnl_pips} pips
                    &nbsp;·&nbsp;
                    {metrics.total_return_pct >= 0 ? '+' : ''}{metrics.total_return_pct}% return
                </div>
            </div>

            {/* Metrics Grid */}
            <div className="metrics-grid">
                {metricCards.slice(2).map((card, i) => (
                    <div className="metric-card" key={i}>
                        <div className="metric-label">{card.label}</div>
                        <div className={`metric-value ${card.positive ? 'text-profit' : ''} ${card.negative ? 'text-loss' : ''}`}>
                            {card.value}
                        </div>
                        {card.sub && (
                            <div className="metric-sub">{card.sub}</div>
                        )}
                    </div>
                ))}
            </div>
        </div>
    )
}
