import { useState, useCallback } from 'react'
import { connectMT5, disconnectMT5 } from '../api/client'
import './MT5Login.css'

export default function MT5Login({ connected, accountInfo, onStatusChange }) {
    const [server, setServer] = useState('')
    const [login, setLogin] = useState('')
    const [password, setPassword] = useState('')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState('')

    const handleConnect = useCallback(async (e) => {
        e.preventDefault()
        setError('')
        setLoading(true)
        try {
            const result = await connectMT5(server, login, password)
            onStatusChange(true, result.account)
        } catch (err) {
            setError(err.message)
        } finally {
            setLoading(false)
        }
    }, [server, login, password, onStatusChange])

    const handleDisconnect = useCallback(async () => {
        setLoading(true)
        try {
            await disconnectMT5()
            onStatusChange(false, null)
        } catch (err) {
            setError(err.message)
        } finally {
            setLoading(false)
        }
    }, [onStatusChange])

    if (connected && accountInfo) {
        return (
            <div className="mt5-connected">
                <div className="connection-status">
                    <span className="status-dot connected" />
                    <span className="status-text">MT5 Connected</span>
                </div>
                <div className="account-details">
                    <div className="detail-row">
                        <span className="detail-label">Account</span>
                        <span className="detail-value">{accountInfo.login}</span>
                    </div>
                    <div className="detail-row">
                        <span className="detail-label">Name</span>
                        <span className="detail-value">{accountInfo.name}</span>
                    </div>
                    <div className="detail-row">
                        <span className="detail-label">Server</span>
                        <span className="detail-value">{accountInfo.server}</span>
                    </div>
                    <div className="detail-row">
                        <span className="detail-label">Balance</span>
                        <span className="detail-value text-profit">
                            {accountInfo.currency} {accountInfo.balance?.toLocaleString()}
                        </span>
                    </div>
                    <div className="detail-row">
                        <span className="detail-label">Broker</span>
                        <span className="detail-value">{accountInfo.company}</span>
                    </div>
                </div>
                <button
                    className="btn btn-disconnect"
                    onClick={handleDisconnect}
                    disabled={loading}
                >
                    {loading ? 'Disconnecting...' : 'Disconnect'}
                </button>
            </div>
        )
    }

    return (
        <form className="mt5-login-form" onSubmit={handleConnect}>
            <div className="connection-status">
                <span className="status-dot disconnected" />
                <span className="status-text">MT5 Disconnected</span>
            </div>

            {error && <div className="error-message">{error}</div>}

            <div className="form-group">
                <label htmlFor="mt5-server">Server</label>
                <input
                    id="mt5-server"
                    type="text"
                    placeholder="e.g. Exness-MT5Real"
                    value={server}
                    onChange={(e) => setServer(e.target.value)}
                    required
                />
            </div>

            <div className="form-group">
                <label htmlFor="mt5-login">Login</label>
                <input
                    id="mt5-login"
                    type="text"
                    placeholder="Account number"
                    value={login}
                    onChange={(e) => setLogin(e.target.value)}
                    required
                />
            </div>

            <div className="form-group">
                <label htmlFor="mt5-password">Password</label>
                <input
                    id="mt5-password"
                    type="password"
                    placeholder="Password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                />
            </div>

            <button className="btn btn-primary" type="submit" disabled={loading}>
                {loading ? (
                    <span className="btn-loading">
                        <span className="spinner" /> Connecting...
                    </span>
                ) : (
                    'Connect to MT5'
                )}
            </button>
        </form>
    )
}
