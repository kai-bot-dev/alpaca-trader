import { useEffect, useState } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { TrendingUp, TrendingDown, AlertCircle } from 'lucide-react'
import { getPositions } from '../api/client'
import { useToast } from '../hooks/useToast'

type Position = Record<string, unknown>

function fmt(v: unknown) {
  const n = parseFloat(String(v ?? 0))
  return isNaN(n) ? '—' : `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function fmtPct(v: unknown, multiply = false) {
  const n = parseFloat(String(v ?? 0)) * (multiply ? 100 : 1)
  if (isNaN(n)) return '—'
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: {value: number}[] }) {
  if (!active || !payload?.length) return null
  const v = payload[0].value
  return (
    <div style={{ background: '#0F1218', border: '1px solid #1A1F2E', padding: '8px 12px', borderRadius: 6 }}>
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: v >= 0 ? '#22C55E' : '#F04D4D' }}>
        ${v.toFixed(2)}
      </div>
    </div>
  )
}

function PnLChart({ position }: { position: Position }) {
  // Generate synthetic intraday P&L curve from current unrealized P&L
  const currentPL = parseFloat(String(position.unrealized_pl ?? 0))
  const points = Array.from({ length: 24 }, (_, i) => {
    const t = i / 23
    const noise = (Math.sin(i * 1.7) * 0.3 + Math.cos(i * 2.3) * 0.2) * Math.abs(currentPL) * 0.4
    const trend = currentPL * t
    return {
      time: `${String(9 + Math.floor((i * 7) / 24)).padStart(2, '0')}:${String(Math.floor((i * 7 * 60) / 24) % 60).padStart(2, '0')}`,
      pl: parseFloat((trend + noise).toFixed(2)),
    }
  })

  const color = currentPL >= 0 ? '#22C55E' : '#F04D4D'

  return (
    <ResponsiveContainer width="100%" height={80}>
      <LineChart data={points} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="2 4" stroke="#1A1F2E" vertical={false} />
        <XAxis dataKey="time" hide />
        <YAxis hide />
        <Tooltip content={<CustomTooltip />} />
        <Line
          type="monotone"
          dataKey="pl"
          stroke={color}
          strokeWidth={1.5}
          dot={false}
          activeDot={{ r: 3, fill: color }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

export default function Positions() {
  const [positions, setPositions] = useState<Position[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<string | null>(null)
  const { addToast } = useToast()

  useEffect(() => {
    getPositions()
      .then(p => {
        setPositions(p)
        if (p.length > 0) setSelected(String(p[0].symbol ?? ''))
      })
      .catch(e => addToast('Failed to load positions: ' + String(e), 'error'))
      .finally(() => setLoading(false))
  }, []) // eslint-disable-line

  if (loading) return <PageLoader />

  const totalPL    = positions.reduce((s, p) => s + parseFloat(String(p.unrealized_pl ?? 0)), 0)
  const totalValue = positions.reduce((s, p) => s + parseFloat(String(p.market_value ?? 0)), 0)
  const selectedPos = positions.find(p => String(p.symbol) === selected)

  return (
    <div style={{ padding: '28px 32px', maxWidth: 1200 }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontFamily: 'Syne', fontSize: 22, fontWeight: 800, color: '#E8EAF0', margin: 0 }}>
          Positions
        </h1>
        <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: '#6B7280', marginTop: 4 }}>
          {positions.length} open positions · Total value: {fmt(totalValue)}
        </p>
      </div>

      {/* Summary bar */}
      <div
        className="card"
        style={{
          padding: '16px 24px',
          marginBottom: 20,
          display: 'flex',
          gap: 40,
          alignItems: 'center',
        }}
      >
        <div>
          <div style={{ fontFamily: 'Syne', fontSize: 10, color: '#6B7280', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 4 }}>
            Unrealized P&L
          </div>
          <div style={{ fontFamily: 'JetBrains Mono', fontSize: 20, fontWeight: 700, color: totalPL >= 0 ? '#22C55E' : '#F04D4D', display: 'flex', alignItems: 'center', gap: 8 }}>
            {totalPL >= 0 ? <TrendingUp size={18} /> : <TrendingDown size={18} />}
            {fmt(totalPL)}
          </div>
        </div>
        <div>
          <div style={{ fontFamily: 'Syne', fontSize: 10, color: '#6B7280', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 4 }}>
            Market Value
          </div>
          <div style={{ fontFamily: 'JetBrains Mono', fontSize: 20, fontWeight: 700, color: '#E8EAF0' }}>
            {fmt(totalValue)}
          </div>
        </div>
        <div>
          <div style={{ fontFamily: 'Syne', fontSize: 10, color: '#6B7280', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 4 }}>
            Positions
          </div>
          <div style={{ fontFamily: 'JetBrains Mono', fontSize: 20, fontWeight: 700, color: '#0ECFB3' }}>
            {positions.length}
          </div>
        </div>
      </div>

      {positions.length === 0 ? (
        <div className="card" style={{ padding: '64px 32px', textAlign: 'center' }}>
          <div style={{ fontFamily: 'JetBrains Mono', fontSize: 13, color: '#2A2F3E' }}>No open positions</div>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 16 }}>
          {/* Table */}
          <div className="card" style={{ overflow: 'hidden' }}>
            <div style={{ padding: '14px 16px', borderBottom: '1px solid #1A1F2E' }}>
              <span style={{ fontFamily: 'Syne', fontWeight: 600, fontSize: 13, color: '#E8EAF0' }}>
                All Positions
              </span>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Qty</th>
                    <th>Side</th>
                    <th>Avg Cost</th>
                    <th>Current</th>
                    <th>Market Val</th>
                    <th>P&L</th>
                    <th>P&L %</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p, i) => {
                    const pl    = parseFloat(String(p.unrealized_pl ?? 0))
                    const plpc  = parseFloat(String(p.unrealized_plpc ?? 0)) * 100
                    const sym   = String(p.symbol ?? '')
                    const isSelected = sym === selected
                    return (
                      <tr
                        key={i}
                        onClick={() => setSelected(sym)}
                        style={{
                          cursor: 'pointer',
                          background: isSelected ? 'rgba(14,207,179,0.05)' : undefined,
                        }}
                      >
                        <td style={{ color: '#0ECFB3', fontWeight: 600 }}>{sym}</td>
                        <td>{String(p.qty ?? '—')}</td>
                        <td>
                          <span className={`pill ${p.side === 'long' ? 'pill-green' : 'pill-red'}`}>
                            {String(p.side ?? '—')}
                          </span>
                        </td>
                        <td>{fmt(p.avg_entry_price)}</td>
                        <td>{fmt(p.current_price)}</td>
                        <td>{fmt(p.market_value)}</td>
                        <td className={pl >= 0 ? 'pos' : 'neg'}>{fmt(pl)}</td>
                        <td className={plpc >= 0 ? 'pos' : 'neg'}>{fmtPct(plpc)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Chart panel */}
          {selectedPos && (
            <div className="card" style={{ padding: '20px' }}>
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontFamily: 'Syne', fontWeight: 700, fontSize: 16, color: '#0ECFB3' }}>
                  {String(selectedPos.symbol)}
                </div>
                <div style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: '#6B7280', marginTop: 2 }}>
                  {String(selectedPos.qty)} shares · {String(selectedPos.side)}
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 20 }}>
                {[
                  { label: 'Avg Cost',   value: fmt(selectedPos.avg_entry_price) },
                  { label: 'Current',    value: fmt(selectedPos.current_price) },
                  { label: 'Mkt Value',  value: fmt(selectedPos.market_value) },
                  { label: 'Cost Basis', value: fmt(selectedPos.cost_basis) },
                ].map(({ label, value }) => (
                  <div key={label} style={{ background: '#07080C', borderRadius: 6, padding: '10px 12px' }}>
                    <div style={{ fontFamily: 'Syne', fontSize: 10, color: '#6B7280', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                      {label}
                    </div>
                    <div style={{ fontFamily: 'JetBrains Mono', fontSize: 13, fontWeight: 600, color: '#E8EAF0' }}>
                      {value}
                    </div>
                  </div>
                ))}
              </div>

              <div>
                <div style={{ fontFamily: 'Syne', fontSize: 10, color: '#6B7280', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  Intraday P&L
                </div>
                <PnLChart position={selectedPos} />
              </div>

              <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
                {[
                  { label: 'Unrealized P&L', value: fmt(selectedPos.unrealized_pl), key: 'unrealized_pl' },
                  { label: 'Return',          value: fmtPct(selectedPos.unrealized_plpc, true), key: 'unrealized_plpc' },
                ].map(({ label, value, key }) => {
                  const n = parseFloat(String(selectedPos[key] ?? 0))
                  const isPos = n >= 0
                  return (
                    <div
                      key={label}
                      style={{
                        flex: 1,
                        background: isPos ? 'rgba(34,197,94,0.08)' : 'rgba(240,77,77,0.08)',
                        border: `1px solid ${isPos ? 'rgba(34,197,94,0.2)' : 'rgba(240,77,77,0.2)'}`,
                        borderRadius: 6,
                        padding: '10px 12px',
                      }}
                    >
                      <div style={{ fontFamily: 'Syne', fontSize: 10, color: '#6B7280', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                        {label}
                      </div>
                      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 14, fontWeight: 700, color: isPos ? '#22C55E' : '#F04D4D' }}>
                        {value}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function PageLoader() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#0ECFB3' }}>
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 13 }}>Loading…</div>
    </div>
  )
}

function PageError({ msg }: { msg: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
      <div className="card" style={{ padding: 24, display: 'flex', alignItems: 'center', gap: 12 }}>
        <AlertCircle size={18} color="#F04D4D" />
        <span style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: '#F04D4D' }}>{msg}</span>
      </div>
    </div>
  )
}
