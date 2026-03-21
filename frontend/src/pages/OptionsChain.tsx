import { useState } from 'react'
import { Search, AlertCircle, Link2 } from 'lucide-react'
import { getChain } from '../api/client'

type OptionRow = Record<string, unknown>

function fmt2(v: unknown) {
  const n = parseFloat(String(v ?? 0))
  return isNaN(n) ? '—' : n.toFixed(2)
}

function fmt4(v: unknown) {
  const n = parseFloat(String(v ?? 0))
  return isNaN(n) ? '—' : n.toFixed(4)
}

function fmtPrice(v: unknown) {
  const n = parseFloat(String(v ?? 0))
  return isNaN(n) ? '—' : `$${n.toFixed(2)}`
}

function greekColor(name: string, val: number) {
  if (name === 'delta') return val > 0 ? '#0ECFB3' : '#F04D4D'
  if (name === 'theta') return '#F8A43A'
  if (name === 'gamma') return '#5EEAD4'
  if (name === 'vega')  return '#A78BFA'
  return '#E8EAF0'
}

function ChainTable({ rows, type }: { rows: OptionRow[]; type: 'call' | 'put' }) {
  if (!rows || rows.length === 0) {
    return (
      <div style={{ padding: '32px 16px', textAlign: 'center', fontFamily: 'JetBrains Mono', fontSize: 12, color: '#2A2F3E' }}>
        No {type}s available
      </div>
    )
  }
  const isCall = type === 'call'
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data-table">
        <thead>
          <tr>
            <th>Strike</th>
            <th>Expiry</th>
            <th>Bid</th>
            <th>Ask</th>
            <th>Last</th>
            <th>Vol</th>
            <th>OI</th>
            <th>IV</th>
            <th>Δ Delta</th>
            <th>Γ Gamma</th>
            <th>Θ Theta</th>
            <th>ν Vega</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const delta = parseFloat(String(row.delta ?? 0))
            const inMoney = isCall ? delta > 0.5 : delta < -0.5
            return (
              <tr
                key={i}
                style={{
                  background: inMoney ? 'rgba(14,207,179,0.03)' : undefined,
                }}
              >
                <td style={{ color: '#0ECFB3', fontWeight: 600 }}>{fmtPrice(row.strike_price)}</td>
                <td style={{ color: '#6B7280' }}>{String(row.expiration_date ?? '—')}</td>
                <td>{fmtPrice(row.bid_price)}</td>
                <td>{fmtPrice(row.ask_price)}</td>
                <td style={{ fontWeight: 600 }}>{fmtPrice(row.last_trade_price)}</td>
                <td style={{ color: '#6B7280' }}>{String(row.volume ?? '—')}</td>
                <td style={{ color: '#6B7280' }}>{String(row.open_interest ?? '—')}</td>
                <td style={{ color: '#F8A43A' }}>{fmt2(row.implied_volatility ? parseFloat(String(row.implied_volatility)) * 100 : null)}%</td>
                <td style={{ color: greekColor('delta', delta), fontWeight: 500 }}>{fmt4(row.delta)}</td>
                <td style={{ color: greekColor('gamma', 0), fontWeight: 500 }}>{fmt4(row.gamma)}</td>
                <td style={{ color: greekColor('theta', 0), fontWeight: 500 }}>{fmt4(row.theta)}</td>
                <td style={{ color: greekColor('vega', 0), fontWeight: 500 }}>{fmt4(row.vega)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function OptionsChain() {
  const [symbol, setSymbol] = useState('')
  const [input, setInput] = useState('')
  const [chain, setChain] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<'call' | 'put'>('call')

  const search = async () => {
    const s = input.trim().toUpperCase()
    if (!s) return
    setLoading(true)
    setError(null)
    setChain(null)
    try {
      const data = await getChain(s)
      setChain(data)
      setSymbol(s)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  const calls = (chain?.calls as OptionRow[]) ?? []
  const puts  = (chain?.puts  as OptionRow[]) ?? []

  return (
    <div style={{ padding: '28px 32px', maxWidth: 1200 }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontFamily: 'Syne', fontSize: 22, fontWeight: 800, color: '#E8EAF0', margin: 0 }}>
          Options Chain
        </h1>
        <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: '#6B7280', marginTop: 4 }}>
          View calls, puts, and Greeks for any equity or ETF
        </p>
      </div>

      {/* Search bar */}
      <div
        className="card"
        style={{ padding: '16px 20px', marginBottom: 20, display: 'flex', gap: 12, alignItems: 'center' }}
      >
        <Link2 size={16} color="#0ECFB3" />
        <input
          className="field"
          style={{ maxWidth: 200 }}
          placeholder="Ticker (e.g. AAPL)"
          value={input}
          onChange={e => setInput(e.target.value.toUpperCase())}
          onKeyDown={e => e.key === 'Enter' && search()}
        />
        <button className="btn btn-teal" onClick={search} disabled={loading}>
          <Search size={14} />
          {loading ? 'Loading…' : 'Fetch Chain'}
        </button>
        {symbol && chain && (
          <span style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: '#0ECFB3', marginLeft: 8 }}>
            {symbol} · {calls.length} calls, {puts.length} puts
          </span>
        )}
      </div>

      {error && (
        <div className="card" style={{ padding: '14px 16px', marginBottom: 16, display: 'flex', gap: 10, alignItems: 'center', borderColor: 'rgba(240,77,77,0.3)' }}>
          <AlertCircle size={16} color="#F04D4D" />
          <span style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: '#F04D4D' }}>{error}</span>
        </div>
      )}

      {chain && (
        <div className="card" style={{ overflow: 'hidden' }}>
          {/* Tabs */}
          <div style={{ display: 'flex', borderBottom: '1px solid #1A1F2E' }}>
            {(['call', 'put'] as const).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                style={{
                  padding: '12px 24px',
                  fontFamily: 'Syne',
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: 'pointer',
                  border: 'none',
                  background: 'transparent',
                  color: tab === t ? '#0ECFB3' : '#6B7280',
                  borderBottom: `2px solid ${tab === t ? '#0ECFB3' : 'transparent'}`,
                  transition: 'all 0.12s',
                }}
              >
                {t === 'call' ? `Calls (${calls.length})` : `Puts (${puts.length})`}
              </button>
            ))}
          </div>

          <ChainTable rows={tab === 'call' ? calls : puts} type={tab} />
        </div>
      )}

      {!chain && !loading && !error && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '80px 20px',
            color: '#2A2F3E',
          }}
        >
          <Link2 size={40} style={{ marginBottom: 16 }} />
          <div style={{ fontFamily: 'JetBrains Mono', fontSize: 13 }}>Enter a ticker to load the options chain</div>
        </div>
      )}
    </div>
  )
}
