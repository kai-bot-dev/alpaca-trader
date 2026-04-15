import { useEffect, useState, useCallback } from 'react'
import { Activity, RefreshCw, TrendingUp, TrendingDown, Minus, Bell, BellOff, CheckCircle, Clock } from 'lucide-react'
import { getWatchlist, getAlerts, dismissAlert, checkAlerts, getMonitorStatus } from '../api/client'
import { useToast } from '../hooks/useToast'

type WatchItem = Record<string, unknown>
type AlertItem = Record<string, unknown>

function TrendIcon({ trend }: { trend: string }) {
  if (trend === 'up')   return <TrendingUp  size={14} color="#22C55E" />
  if (trend === 'down') return <TrendingDown size={14} color="#F04D4D" />
  return <Minus size={14} color="#6B7280" />
}

function ScanResult({ result }: { result: Record<string, unknown> }) {
  const signal = String(result.signal ?? '')
  const score  = parseFloat(String(result.score ?? 0))
  const isLong = signal === 'long' || signal === 'buy'
  const isShort = signal === 'short' || signal === 'sell'
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '10px 16px',
        borderBottom: '1px solid rgba(26,31,46,0.5)',
      }}
    >
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 13, fontWeight: 700, color: '#0ECFB3', width: 60 }}>
        {String(result.symbol ?? '—')}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontFamily: 'Syne', fontSize: 12, color: '#E8EAF0' }}>
          {String(result.strategy ?? 'BB Band Walk')}
        </div>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: '#6B7280', marginTop: 2 }}>
          {String(result.reason ?? '—')}
        </div>
      </div>
      <div style={{ textAlign: 'right' }}>
        <span className={`pill ${isLong ? 'pill-green' : isShort ? 'pill-red' : 'pill-gray'}`}>
          {signal || 'neutral'}
        </span>
      </div>
      <div style={{ width: 60, textAlign: 'right' }}>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: score > 0.6 ? '#22C55E' : score < 0.4 ? '#F04D4D' : '#6B7280' }}>
          {isNaN(score) ? '—' : (score * 100).toFixed(0)}
        </div>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, color: '#2A2F3E' }}>SCORE</div>
      </div>
    </div>
  )
}

function AlertRow({ alert, onDismiss }: { alert: AlertItem; onDismiss: (id: number) => void }) {
  const status = String(alert.status ?? 'active')
  const alertType = String(alert.alert_type ?? '')
  const symbol = String(alert.symbol ?? '—')
  const condition = (alert.condition as Record<string, unknown>) ?? {}
  const message = String(alert.message ?? '')
  const createdAt = String(alert.created_at ?? '').slice(0, 16)

  const statusColor = status === 'active' ? '#0ECFB3' : status === 'triggered' ? '#F8A43A' : '#6B7280'
  const condStr = Object.entries(condition).map(([k, v]) => `${k}=${v}`).join(', ')

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      padding: '10px 16px',
      borderBottom: '1px solid rgba(26,31,46,0.5)',
    }}>
      <div style={{ width: 8, height: 8, borderRadius: '50%', background: statusColor, flexShrink: 0 }} />
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 12, fontWeight: 700, color: '#0ECFB3', width: 56 }}>
        {symbol}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontFamily: 'Syne', fontSize: 12, color: '#E8EAF0', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          {alertType}
        </div>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: '#6B7280', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {message || condStr || '—'}
        </div>
      </div>
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: '#6B7280', flexShrink: 0 }}>
        {createdAt}
      </div>
      <span style={{
        fontFamily: 'JetBrains Mono', fontSize: 10,
        padding: '2px 8px', borderRadius: 99,
        background: status === 'active' ? 'rgba(14,207,179,0.1)' : status === 'triggered' ? 'rgba(248,164,58,0.1)' : 'rgba(107,114,128,0.1)',
        color: statusColor,
        flexShrink: 0,
      }}>
        {status}
      </span>
      {status !== 'dismissed' && (
        <button
          onClick={() => onDismiss(Number(alert.id))}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: '#2A2F3E', flexShrink: 0 }}
          title="Dismiss"
        >
          <BellOff size={13} />
        </button>
      )}
    </div>
  )
}

export default function StrategyMonitor() {
  const [watchlist, setWatchlist] = useState<WatchItem[]>([])
  const [loading, setLoading]     = useState(true)
  const [scanning, setScanning]   = useState(false)
  const { addToast } = useToast()

  const [alerts, setAlerts]           = useState<AlertItem[]>([])
  const [alertsLoading, setAlertsLoading] = useState(true)
  const [checking, setChecking]       = useState(false)
  const [monitorStatus, setMonitorStatus] = useState<Record<string, unknown> | null>(null)

  // Mock scan results – in a real setup this would come from a /api/scan endpoint
  const [scanResults] = useState<Record<string, unknown>[]>([])

  const loadAlerts = useCallback(() => {
    setAlertsLoading(true)
    getAlerts({ status: 'active' })
      .then(a => setAlerts(a))
      .catch(e => {
        addToast('Failed to load alerts: ' + String(e), 'error')
        setAlerts([])
      })
      .finally(() => setAlertsLoading(false))
  }, [addToast])

  useEffect(() => {
    getWatchlist()
      .then(w => setWatchlist(w))
      .catch(e => addToast('Failed to load watchlist: ' + String(e), 'error'))
      .finally(() => setLoading(false))

    loadAlerts()

    getMonitorStatus()
      .then(s => setMonitorStatus(s))
      .catch(e => {
        addToast('Failed to load monitor status: ' + String(e), 'error')
        setMonitorStatus(null)
      })
  }, [loadAlerts, addToast])

  const runScan = () => {
    setScanning(true)
    setTimeout(() => setScanning(false), 2000)
  }

  const handleCheckAlerts = () => {
    setChecking(true)
    checkAlerts()
      .then(() => loadAlerts())
      .catch(e => addToast('Failed to check alerts: ' + String(e), 'error'))
      .finally(() => setChecking(false))
  }

  const handleDismiss = (id: number) => {
    dismissAlert(id)
      .then(() => loadAlerts())
      .catch(e => addToast('Failed to dismiss alert: ' + String(e), 'error'))
  }

  const triggeredAlerts = alerts.filter(a => String(a.status) === 'triggered')
  const activeAlerts = alerts.filter(a => String(a.status) === 'active')

  return (
    <div style={{ padding: '28px 32px', maxWidth: 1200 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontFamily: 'Syne', fontSize: 22, fontWeight: 800, color: '#E8EAF0', margin: 0 }}>
            Strategy Monitor
          </h1>
          <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: '#6B7280', marginTop: 4 }}>
            Watchlist scanning · BB Band Walk + MACD
          </p>
        </div>
        <button
          className="btn btn-teal"
          onClick={runScan}
          disabled={scanning}
          style={{ display: 'flex', alignItems: 'center', gap: 8 }}
        >
          <RefreshCw size={14} style={{ animation: scanning ? 'spin 1s linear infinite' : undefined }} />
          {scanning ? 'Scanning…' : 'Run Scan'}
        </button>
      </div>



      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Watchlist */}
        <div className="card" style={{ overflow: 'hidden' }}>
          <div style={{ padding: '14px 16px', borderBottom: '1px solid #1A1F2E', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Activity size={14} color="#0ECFB3" />
            <span style={{ fontFamily: 'Syne', fontWeight: 600, fontSize: 13, color: '#E8EAF0' }}>
              Watchlist
            </span>
            <span
              style={{
                marginLeft: 'auto',
                fontFamily: 'JetBrains Mono',
                fontSize: 11,
                color: '#6B7280',
                background: '#1A1F2E',
                padding: '2px 8px',
                borderRadius: 99,
              }}
            >
              {watchlist.length}
            </span>
          </div>

          {loading ? (
            <div style={{ padding: '32px 16px', textAlign: 'center', fontFamily: 'JetBrains Mono', fontSize: 12, color: '#6B7280' }}>
              Loading…
            </div>
          ) : watchlist.length === 0 ? (
            <div style={{ padding: '48px 16px', textAlign: 'center', fontFamily: 'JetBrains Mono', fontSize: 12, color: '#2A2F3E' }}>
              Watchlist empty — add symbols in Settings
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Name</th>
                  <th>Price</th>
                  <th>Change</th>
                  <th>Trend</th>
                </tr>
              </thead>
              <tbody>
                {watchlist.map((item, i) => {
                  const change = parseFloat(String(item.change_pct ?? 0))
                  const trend  = change > 0.5 ? 'up' : change < -0.5 ? 'down' : 'flat'
                  return (
                    <tr key={i}>
                      <td style={{ color: '#0ECFB3', fontWeight: 600 }}>{String(item.symbol ?? '—')}</td>
                      <td style={{ color: '#6B7280', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {String(item.name ?? item.symbol ?? '—')}
                      </td>
                      <td>
                        {item.price ? `$${parseFloat(String(item.price)).toFixed(2)}` : '—'}
                      </td>
                      <td className={change >= 0 ? 'pos' : 'neg'}>
                        {isNaN(change) ? '—' : `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`}
                      </td>
                      <td><TrendIcon trend={trend} /></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Scan results */}
        <div className="card" style={{ overflow: 'hidden' }}>
          <div style={{ padding: '14px 16px', borderBottom: '1px solid #1A1F2E', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Activity size={14} color="#F8A43A" />
            <span style={{ fontFamily: 'Syne', fontWeight: 600, fontSize: 13, color: '#E8EAF0' }}>
              Scan Results
            </span>
            {scanning && (
              <span style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: '#F8A43A', marginLeft: 'auto' }}>
                Scanning watchlist…
              </span>
            )}
          </div>

          {scanResults.length === 0 ? (
            <div style={{ padding: '48px 24px', textAlign: 'center' }}>
              <Activity size={32} color="#1A1F2E" style={{ margin: '0 auto 16px' }} />
              <div style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: '#2A2F3E', marginBottom: 8 }}>
                No scan results
              </div>
              <div style={{ fontFamily: 'Syne', fontSize: 12, color: '#6B7280' }}>
                Run a scan to find BB Band Walk signals
              </div>
            </div>
          ) : (
            scanResults.map((r, i) => <ScanResult key={i} result={r} />)
          )}
        </div>
      </div>

      {/* Alerts Section */}
      <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Active Alerts */}
        <div className="card" style={{ overflow: 'hidden' }}>
          <div style={{ padding: '14px 16px', borderBottom: '1px solid #1A1F2E', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Bell size={14} color="#0ECFB3" />
            <span style={{ fontFamily: 'Syne', fontWeight: 600, fontSize: 13, color: '#E8EAF0' }}>
              Active Alerts
            </span>
            <span style={{
              marginLeft: 'auto',
              fontFamily: 'JetBrains Mono', fontSize: 11, color: '#6B7280',
              background: '#1A1F2E', padding: '2px 8px', borderRadius: 99,
            }}>
              {activeAlerts.length}
            </span>
            <button
              className="btn btn-teal"
              onClick={handleCheckAlerts}
              disabled={checking}
              style={{ padding: '4px 10px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 6 }}
            >
              <RefreshCw size={11} style={{ animation: checking ? 'spin 1s linear infinite' : undefined }} />
              {checking ? 'Checking…' : 'Check Now'}
            </button>
          </div>

          {alertsLoading ? (
            <div style={{ padding: '32px 16px', textAlign: 'center', fontFamily: 'JetBrains Mono', fontSize: 12, color: '#6B7280' }}>
              Loading…
            </div>
          ) : activeAlerts.length === 0 ? (
            <div style={{ padding: '36px 24px', textAlign: 'center' }}>
              <CheckCircle size={28} color="#1A1F2E" style={{ margin: '0 auto 12px' }} />
              <div style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: '#2A2F3E' }}>
                No active alerts
              </div>
            </div>
          ) : (
            activeAlerts.map((a, i) => (
              <AlertRow key={i} alert={a} onDismiss={handleDismiss} />
            ))
          )}
        </div>

        {/* Monitor Status + Triggered Alerts */}
        <div className="card" style={{ overflow: 'hidden' }}>
          <div style={{ padding: '14px 16px', borderBottom: '1px solid #1A1F2E', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Clock size={14} color="#F8A43A" />
            <span style={{ fontFamily: 'Syne', fontWeight: 600, fontSize: 13, color: '#E8EAF0' }}>
              Monitor Status
            </span>
          </div>

          {/* Status info */}
          {monitorStatus && (
            <div style={{ padding: '12px 16px', borderBottom: '1px solid #1A1F2E', display: 'flex', gap: 24 }}>
              <div>
                <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, color: '#2A2F3E', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
                  Last Run
                </div>
                <div style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: '#6B7280', marginTop: 2 }}>
                  {monitorStatus.last_run ? String(monitorStatus.last_run).slice(0, 16) : 'never'}
                </div>
              </div>
              <div>
                <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, color: '#2A2F3E', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
                  Active Alerts
                </div>
                <div style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: '#0ECFB3', marginTop: 2 }}>
                  {String(monitorStatus.active_alerts ?? 0)}
                </div>
              </div>
              <div>
                <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, color: '#2A2F3E', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
                  Schedule
                </div>
                <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: '#6B7280', marginTop: 2 }}>
                  Every 15min (market hours)
                </div>
              </div>
            </div>
          )}

          {/* Triggered alerts */}
          <div style={{ padding: '10px 16px', borderBottom: '1px solid #1A1F2E' }}>
            <span style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Recently Triggered
            </span>
          </div>
          {triggeredAlerts.length === 0 ? (
            <div style={{ padding: '24px 16px', textAlign: 'center', fontFamily: 'JetBrains Mono', fontSize: 11, color: '#2A2F3E' }}>
              No triggered alerts
            </div>
          ) : (
            triggeredAlerts.slice(0, 6).map((a, i) => (
              <AlertRow key={i} alert={a} onDismiss={handleDismiss} />
            ))
          )}
        </div>
      </div>

      {/* Strategy info */}
      <div className="card" style={{ padding: '20px 24px', marginTop: 16 }}>
        <div style={{ fontFamily: 'Syne', fontWeight: 600, fontSize: 13, color: '#E8EAF0', marginBottom: 16 }}>
          Active Strategies
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          {[
            {
              name: 'BB Band Walk',
              desc: 'Bollinger Band walking with trend detection. Long when price walks upper band, short when walking lower.',
              status: 'active',
              color: '#0ECFB3',
            },
            {
              name: 'MACD Confirmation',
              desc: 'MACD crossover confirmation for BB Band Walk signals. Filters false breakouts.',
              status: 'active',
              color: '#0ECFB3',
            },
            {
              name: 'Multi-Leg Options',
              desc: 'Spreads and complex options strategies with defined risk parameters.',
              status: 'ready',
              color: '#F8A43A',
            },
          ].map(s => (
            <div key={s.name} style={{ background: '#07080C', borderRadius: 6, padding: '14px 16px', border: '1px solid #1A1F2E' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                <div style={{ fontFamily: 'Syne', fontWeight: 600, fontSize: 13, color: s.color }}>
                  {s.name}
                </div>
                <span className={`pill ${s.status === 'active' ? 'pill-green' : 'pill-amber'}`}>
                  {s.status}
                </span>
              </div>
              <div style={{ fontFamily: 'Syne', fontSize: 12, color: '#6B7280', lineHeight: 1.5 }}>
                {s.desc}
              </div>
            </div>
          ))}
        </div>
      </div>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
    </div>
  )
}
