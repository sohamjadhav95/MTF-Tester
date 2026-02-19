import { useState, useEffect, useCallback } from 'react'
import { getSymbols, getTimeframes, getStrategies, getStrategySettings } from '../api/client'
import './AssetConfig.css'

export default function AssetConfig({ connected, config, onConfigChange }) {
    const [symbols, setSymbols] = useState([])
    const [timeframes, setTimeframes] = useState([])
    const [strategies, setStrategies] = useState([])
    const [strategySettings, setStrategySettings] = useState(null)
    const [settingsValues, setSettingsValues] = useState({})
    const [symbolSearch, setSymbolSearch] = useState('')
    const [loading, setLoading] = useState(false)

    // Load symbols, timeframes, strategies when connected
    useEffect(() => {
        if (!connected) return
        const load = async () => {
            setLoading(true)
            try {
                const [symRes, tfRes, stratRes] = await Promise.all([
                    getSymbols(),
                    getTimeframes(),
                    getStrategies(),
                ])
                setSymbols(symRes.symbols || [])
                setTimeframes(tfRes.timeframes || [])
                setStrategies(stratRes.strategies || [])
            } catch (err) {
                console.error('Failed to load config data:', err)
            } finally {
                setLoading(false)
            }
        }
        load()
    }, [connected])

    // Load strategy settings when strategy changes
    useEffect(() => {
        if (!config.strategy) {
            setStrategySettings(null)
            return
        }
        const loadSettings = async () => {
            try {
                const res = await getStrategySettings(config.strategy)
                setStrategySettings(res.settings)
                // Initialize settings with defaults
                const defaults = {}
                Object.entries(res.settings).forEach(([key, spec]) => {
                    defaults[key] = config.settings?.[key] ?? spec.default
                })
                setSettingsValues(defaults)
                onConfigChange({ ...config, settings: defaults })
            } catch (err) {
                console.error('Failed to load strategy settings:', err)
            }
        }
        loadSettings()
    }, [config.strategy])

    const updateConfig = useCallback((key, value) => {
        const updated = { ...config, [key]: value }
        onConfigChange(updated)
    }, [config, onConfigChange])

    const updateSetting = useCallback((key, value) => {
        const updated = { ...settingsValues, [key]: value }
        setSettingsValues(updated)
        onConfigChange({ ...config, settings: updated })
    }, [settingsValues, config, onConfigChange])

    const filteredSymbols = symbols.filter(s =>
        s.name.toLowerCase().includes(symbolSearch.toLowerCase()) ||
        s.description?.toLowerCase().includes(symbolSearch.toLowerCase())
    )

    if (!connected) {
        return (
            <div className="config-disabled">
                <div className="disabled-icon">🔌</div>
                <p>Connect to MT5 to configure your backtest</p>
            </div>
        )
    }

    if (loading) {
        return (
            <div className="config-loading">
                <span className="spinner-lg" />
                <p>Loading market data...</p>
            </div>
        )
    }

    return (
        <div className="asset-config">
            {/* Symbol Selection */}
            <div className="config-section">
                <h3 className="config-section-title">Asset Symbol</h3>
                <div className="form-group">
                    <input
                        type="text"
                        placeholder="Search symbols (e.g. EURUSD)"
                        value={symbolSearch}
                        onChange={(e) => setSymbolSearch(e.target.value)}
                        className="symbol-search"
                    />
                </div>
                <div className="symbol-list">
                    {filteredSymbols.slice(0, 50).map(s => (
                        <button
                            key={s.name}
                            className={`symbol-item ${config.symbol === s.name ? 'active' : ''}`}
                            onClick={() => {
                                updateConfig('symbol', s.name)
                                setSymbolSearch(s.name)
                            }}
                        >
                            <span className="symbol-name">{s.name}</span>
                            <span className="symbol-spread">
                                {s.spread} pts
                            </span>
                        </button>
                    ))}
                    {filteredSymbols.length === 0 && (
                        <div className="no-results">No symbols found</div>
                    )}
                </div>
            </div>

            {/* Timeframe */}
            <div className="config-section">
                <h3 className="config-section-title">Timeframe</h3>
                <div className="timeframe-grid">
                    {timeframes.map(tf => (
                        <button
                            key={tf.value}
                            className={`tf-btn ${config.timeframe === tf.value ? 'active' : ''}`}
                            onClick={() => updateConfig('timeframe', tf.value)}
                        >
                            {tf.value}
                        </button>
                    ))}
                </div>
            </div>

            {/* Date Range */}
            <div className="config-section">
                <h3 className="config-section-title">Test Range</h3>
                <div className="date-range">
                    <div className="form-group">
                        <label>From</label>
                        <input
                            type="datetime-local"
                            value={config.dateFrom || ''}
                            onChange={(e) => updateConfig('dateFrom', e.target.value)}
                        />
                    </div>
                    <div className="form-group">
                        <label>To</label>
                        <input
                            type="datetime-local"
                            value={config.dateTo || ''}
                            onChange={(e) => updateConfig('dateTo', e.target.value)}
                        />
                    </div>
                </div>
            </div>

            {/* Strategy Selection */}
            <div className="config-section">
                <h3 className="config-section-title">Strategy</h3>
                <div className="form-group">
                    <select
                        value={config.strategy || ''}
                        onChange={(e) => updateConfig('strategy', e.target.value)}
                    >
                        <option value="">Select a strategy...</option>
                        {strategies.map(s => (
                            <option key={s.name} value={s.name}>{s.name}</option>
                        ))}
                    </select>
                </div>
                {strategies.find(s => s.name === config.strategy)?.description && (
                    <p className="strategy-description">
                        {strategies.find(s => s.name === config.strategy).description}
                    </p>
                )}
            </div>

            {/* Strategy Settings */}
            {strategySettings && Object.keys(strategySettings).length > 0 && (
                <div className="config-section">
                    <h3 className="config-section-title">Strategy Settings</h3>
                    <div className="settings-grid">
                        {Object.entries(strategySettings).map(([key, spec]) => (
                            <div className="setting-item" key={key}>
                                <label className="setting-label">{spec.description || key}</label>
                                {spec.type === 'int' || spec.type === 'float' ? (
                                    <div className="setting-numeric">
                                        <input
                                            type="number"
                                            value={settingsValues[key] ?? spec.default}
                                            min={spec.min}
                                            max={spec.max}
                                            step={spec.step || (spec.type === 'float' ? 0.1 : 1)}
                                            onChange={(e) => updateSetting(key,
                                                spec.type === 'int' ? parseInt(e.target.value) : parseFloat(e.target.value)
                                            )}
                                        />
                                        {spec.min !== undefined && (
                                            <span className="setting-range">{spec.min} — {spec.max}</span>
                                        )}
                                    </div>
                                ) : spec.type === 'select' ? (
                                    <select
                                        value={settingsValues[key] ?? spec.default}
                                        onChange={(e) => updateSetting(key, e.target.value)}
                                    >
                                        {spec.options?.map(opt => (
                                            <option key={opt} value={opt}>
                                                {opt.replace(/_/g, ' ')}
                                            </option>
                                        ))}
                                    </select>
                                ) : spec.type === 'bool' ? (
                                    <label className="toggle-switch">
                                        <input
                                            type="checkbox"
                                            checked={settingsValues[key] ?? spec.default}
                                            onChange={(e) => updateSetting(key, e.target.checked)}
                                        />
                                        <span className="toggle-slider" />
                                    </label>
                                ) : null}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Backtest Settings */}
            <div className="config-section">
                <h3 className="config-section-title">Backtest Settings</h3>
                <div className="settings-grid">
                    <div className="setting-item">
                        <label className="setting-label">Initial Balance</label>
                        <input
                            type="number"
                            value={config.initialBalance || 10000}
                            min={100}
                            step={100}
                            onChange={(e) => updateConfig('initialBalance', parseFloat(e.target.value))}
                        />
                    </div>
                    <div className="setting-item">
                        <label className="setting-label">Lot Size</label>
                        <input
                            type="number"
                            value={config.lotSize || 0.1}
                            min={0.01}
                            max={100}
                            step={0.01}
                            onChange={(e) => updateConfig('lotSize', parseFloat(e.target.value))}
                        />
                    </div>
                </div>
            </div>
        </div>
    )
}
