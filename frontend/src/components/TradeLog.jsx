import { useState } from 'react'
import './TradeLog.css'

export default function TradeLog({ trades }) {
    const [sortField, setSortField] = useState(null)
    const [sortDir, setSortDir] = useState('asc')

    if (!trades || trades.length === 0) return null

    const handleSort = (field) => {
        if (sortField === field) {
            setSortDir(d => d === 'asc' ? 'desc' : 'asc')
        } else {
            setSortField(field)
            setSortDir('asc')
        }
    }

    // Sort trades
    let sortedTrades = [...trades]
    if (sortField) {
        sortedTrades.sort((a, b) => {
            let va = a[sortField]
            let vb = b[sortField]
            if (typeof va === 'string') va = va.toLowerCase()
            if (typeof vb === 'string') vb = vb.toLowerCase()
            if (va < vb) return sortDir === 'asc' ? -1 : 1
            if (va > vb) return sortDir === 'asc' ? 1 : -1
            return 0
        })
    }

    const columns = [
        { key: 'index', label: '#', width: '40px' },
        { key: 'direction', label: 'Side', width: '60px' },
        { key: 'entry_time', label: 'Entry Time', width: '150px' },
        { key: 'exit_time', label: 'Exit Time', width: '150px' },
        { key: 'entry_price', label: 'Entry', width: '90px' },
        { key: 'exit_price', label: 'Exit', width: '90px' },
        { key: 'lot_size', label: 'Lots', width: '60px' },
        { key: 'pnl_pips', label: 'P&L (pips)', width: '90px' },
        { key: 'pnl_money', label: 'P&L ($)', width: '90px' },
        { key: 'bars_held', label: 'Bars', width: '55px' },
        { key: 'spread_cost_pips', label: 'Spread', width: '65px' },
    ]

    const formatTime = (t) => {
        if (!t) return '—'
        try {
            const d = new Date(t)
            return d.toLocaleString('en-GB', {
                year: 'numeric', month: '2-digit', day: '2-digit',
                hour: '2-digit', minute: '2-digit',
            })
        } catch {
            return t
        }
    }

    return (
        <div className="trade-log">
            <div className="trade-log-header">
                <h3 className="trade-log-title">Trade Log</h3>
                <span className="trade-count">{trades.length} trades</span>
            </div>
            <div className="table-wrapper">
                <table className="trades-table">
                    <thead>
                        <tr>
                            {columns.map(col => (
                                <th
                                    key={col.key}
                                    style={{ width: col.width }}
                                    onClick={() => col.key !== 'index' && handleSort(col.key)}
                                    className={col.key !== 'index' ? 'sortable' : ''}
                                >
                                    {col.label}
                                    {sortField === col.key && (
                                        <span className="sort-arrow">{sortDir === 'asc' ? ' ↑' : ' ↓'}</span>
                                    )}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {sortedTrades.map((trade, i) => (
                            <tr key={i} className={trade.pnl_pips >= 0 ? 'row-win' : 'row-loss'}>
                                <td className="text-muted">{i + 1}</td>
                                <td>
                                    <span className={`side-badge ${trade.direction === 'BUY' ? 'buy' : 'sell'}`}>
                                        {trade.direction}
                                    </span>
                                </td>
                                <td className="font-mono">{formatTime(trade.entry_time)}</td>
                                <td className="font-mono">{formatTime(trade.exit_time)}</td>
                                <td className="font-mono">{trade.entry_price}</td>
                                <td className="font-mono">{trade.exit_price}</td>
                                <td className="font-mono">{trade.lot_size}</td>
                                <td className={`font-mono ${trade.pnl_pips >= 0 ? 'text-profit' : 'text-loss'}`}>
                                    {trade.pnl_pips >= 0 ? '+' : ''}{trade.pnl_pips}
                                </td>
                                <td className={`font-mono ${trade.pnl_money >= 0 ? 'text-profit' : 'text-loss'}`}>
                                    {trade.pnl_money >= 0 ? '+' : ''}${trade.pnl_money}
                                </td>
                                <td className="font-mono text-muted">{trade.bars_held}</td>
                                <td className="font-mono text-muted">{trade.spread_cost_pips}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}
