import { useState, useCallback } from 'react'
import MT5Login from './components/MT5Login'
import AssetConfig from './components/AssetConfig'
import ResultsDashboard from './components/ResultsDashboard'
import EquityChart from './components/EquityChart'
import TradeLog from './components/TradeLog'
import { runBacktest } from './api/client'
import './App.css'

export default function App() {
    const [marketType, setMarketType] = useState('forex')
    const [mt5Connected, setMt5Connected] = useState(false)
    const [accountInfo, setAccountInfo] = useState(null)
    const [config, setConfig] = useState({
        symbol: '',
        timeframe: 'H1',
        dateFrom: '',
        dateTo: '',
        strategy: '',
        settings: {},
        initialBalance: 10000,
        lotSize: 0.1,
    })
    const [results, setResults] = useState(null)
    const [backtesting, setBacktesting] = useState(false)
    const [error, setError] = useState('')

    const handleMT5StatusChange = useCallback((connected, account) => {
        setMt5Connected(connected)
        setAccountInfo(account)
        if (!connected) {
            setResults(null)
        }
    }, [])

    const handleRunBacktest = useCallback(async () => {
        if (!config.symbol || !config.timeframe || !config.dateFrom || !config.dateTo || !config.strategy) {
            setError('Please fill in all required fields: symbol, timeframe, date range, and strategy.')
            return
        }

        setError('')
        setBacktesting(true)
        setResults(null)

        try {
            const result = await runBacktest({
                symbol: config.symbol,
                timeframe: config.timeframe,
                date_from: config.dateFrom,
                date_to: config.dateTo,
                strategy: config.strategy,
                settings: config.settings || {},
                initial_balance: config.initialBalance,
                lot_size: config.lotSize,
            })
            setResults(result)
        } catch (err) {
            setError(err.message)
        } finally {
            setBacktesting(false)
        }
    }, [config])

    return (
        <div className="app">
            {/* Sidebar */}
            <aside className="sidebar">
                <div className="sidebar-header">
                    <div className="logo">
                        <span className="logo-icon">📊</span>
                        <div>
                            <h1 className="logo-title">Strategy Tester</h1>
                            <span className="logo-sub">Backtesting Engine</span>
                        </div>
                    </div>
                </div>

                {/* Market Type Toggle */}
                <div className="market-toggle">
                    <button
                        className={`toggle-btn ${marketType === 'forex' ? 'active' : ''}`}
                        onClick={() => setMarketType('forex')}
                    >
                        Forex
                    </button>
                    <button
                        className={`toggle-btn ${marketType === 'crypto' ? 'active' : ''}`}
                        onClick={() => setMarketType('crypto')}
                        disabled
                        title="Coming soon"
                    >
                        Crypto
                        <span className="coming-soon">Soon</span>
                    </button>
                </div>

                {/* MT5 Login */}
                <div className="sidebar-section">
                    <MT5Login
                        connected={mt5Connected}
                        accountInfo={accountInfo}
                        onStatusChange={handleMT5StatusChange}
                    />
                </div>
            </aside>

            {/* Main Content */}
            <main className="main-content">
                <div className="content-scroll">
                    {/* Configuration Section */}
                    <section className="section">
                        <div className="section-header">
                            <h2 className="section-title">Configuration</h2>
                            <div className="section-actions">
                                {error && (
                                    <div className="inline-error">{error}</div>
                                )}
                                <button
                                    className="btn btn-run"
                                    onClick={handleRunBacktest}
                                    disabled={backtesting || !mt5Connected}
                                >
                                    {backtesting ? (
                                        <span className="btn-loading">
                                            <span className="spinner" /> Running Backtest...
                                        </span>
                                    ) : (
                                        <>
                                            <span className="run-icon">▶</span>
                                            Run Backtest
                                        </>
                                    )}
                                </button>
                            </div>
                        </div>
                        <div className="config-panel">
                            <AssetConfig
                                connected={mt5Connected}
                                config={config}
                                onConfigChange={setConfig}
                            />
                        </div>
                    </section>

                    {/* Results Section */}
                    {results && (
                        <section className="section results-section">
                            <ResultsDashboard results={results} />

                            <EquityChart results={results} />

                            <TradeLog trades={results.trades} />
                        </section>
                    )}

                    {/* Loading Overlay */}
                    {backtesting && (
                        <div className="backtest-loading">
                            <div className="loading-content">
                                <span className="spinner-xl" />
                                <p className="loading-text">Running backtest...</p>
                                <p className="loading-sub">Processing bars and calculating metrics</p>
                            </div>
                        </div>
                    )}
                </div>
            </main>
        </div>
    )
}
