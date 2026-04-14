import { useEffect, useState } from 'react'
import { TrendingUp, TrendingDown, DollarSign, Activity, AlertCircle } from 'lucide-react'
import { getAccount, getPositions, getOrders } from '../api/client'
import { useToast } from '../hooks/useToast'

type Account = Record<string, unknown>
type Position = Record<string, unknown>
type Order = Record<string, unknown>

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string
  sub?: string
  accent?: 'teal' | 'green' | 'red' | 'amber'
}) {
  const colors: Record<string, string> = {
    teal: '#0ECFB3',
    green: '#22C55E',
    red: '#F04D4D',
    amber: '#F8A43A',
  }
  const c = accent ? colors[accent] : '#E8EAF0'
  return (
    <div className="card" style={{ padding: '20px 24px' }}>
      <div style={{ fontFamily: 'Syne', fontSize: 11, color: '#6B7280', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 22, fontWeight: 700, color: c, marginBottom: 4 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: '#6B7280' }}>
          {sub}
        </div>
      )}
    </div>
  )
}

function fmt(v: unknown, prefix = '$') {
  const n = parseFloat(String(v ?? 0))
  if (isNaN(n)) return '—'
  return `${prefix}${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function fmtPct(v: unknown) {
  const n = parseFloat(String(v ?? 0))
  if (isNaN(n)) return '—'
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

export default function Overview() {
  const [account, setAccount] = useState<Account | null>(null)
  const [positions, setPositions] = useState<Position[]>([])
  const [orders, setOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(true)
  const { addToast } = useToast()

  useEffect(() => {
    const load = async () => {
      try {
        const [a, p, o] = await Promise.all([
          getAccount(),
          getPositions(),
          getOrders(),
        ])
        setAccount(a)
        setPositions(p)
        setOrders(o.slice(0, 10))
      } catch (e) {
        addToast(String(e), 'error')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) return <PageLoader />

  const equity    = parseFloat(String(account?.equity ?? 0))
  const cash      = parseFloat(String(account?.cash ?? 0))
  const plToday   = parseFloat(String(account?.equity ?? 0)) - parseFloat(String(account?.last_equity ?? equity))
  const plPct     = equity > 0 ? (plToday / equity) * 100 : 0

  return (
    <div style={{ padding: '28px 32px', maxWidth: 1200 }}>
      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontFamily: 'Syne', fontSize: 22, fontWeight: 800, color: '#E8EAF0', margin: 0 }}>
          Portfolio Overview
        </h1>
        <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: '#6B7280', marginTop: 4 }}>
          {account?.account_number as string ?? '—'} · {account?.status as string ?? '—'}
        </p>
      </div>

      {/* Stats grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 28 }}>
        <StatCard label="Portfolio Value" value={fmt(account?.equity)} accent="teal" />
        <StatCard label="Cash Available"  value={fmt(cash)} />
        <StatCard
          label="Today's P&L"
          value={fmt(plToday)}
          sub={fmtPct(plPct)}
          accent={plToday >= 0 ? 'green' : 'red'}
        />
        <StatCard label="Open Positions" value={String(positions.length)} accent="amber" />
      </div>

      {/* Positions table */}
      <Section title="Open Positions" icon={<TrendingUp size={14} />} count={positions.length}>
        {positions.length === 0 ? (
          <Empty msg="No open positions" />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Qty</th>
                <th>Side</th>
                <th>Avg Cost</th>
                <th>Market Val</th>
                <th>Unrealized P&L</th>
                <th>P&L %</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => {
                const pl = parseFloat(String(p.unrealized_pl ?? 0))
                const plp = parseFloat(String(p.unrealized_plpc ?? 0)) * 100
                return (
                  <tr key={i}>
                    <td style={{ color: '#0ECFB3', fontWeight: 600 }}>{String(p.symbol ?? '—')}</td>
                    <td>{String(p.qty ?? '—')}</td>
                    <td>
                      <span className={`pill ${p.side === 'long' ? 'pill-green' : 'pill-red'}`}>
                        {String(p.side ?? '—')}
                      </span>
                    </td>
                    <td>{fmt(p.avg_entry_price)}</td>
                    <td>{fmt(p.market_value)}</td>
                    <td className={pl >= 0 ? 'pos' : 'neg'}>{fmt(pl)}</td>
                    <td className={plp >= 0 ? 'pos' : 'neg'}>{fmtPct(plp)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Section>

      {/* Recent orders */}
      <Section title="Recent Orders" icon={<Activity size={14} />} count={orders.length} style={{ marginTop: 16 }}>
        {orders.length === 0 ? (
          <Empty msg="No recent orders" />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Type</th>
                <th>Qty</th>
                <th>Filled</th>
                <th>Price</th>
                <th>Status</th>
                <th>Submitted</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o, i) => {
                const side = String(o.side ?? '')
                const status = String(o.status ?? '')
                return (
                  <tr key={i}>
                    <td style={{ color: '#0ECFB3', fontWeight: 600 }}>{String(o.symbol ?? '—')}</td>
                    <td className={side === 'buy' ? 'pos' : 'neg'}>{side.toUpperCase()}</td>
                    <td style={{ color: '#6B7280' }}>{String(o.type ?? '—')}</td>
                    <td>{String(o.qty ?? '—')}</td>
                    <td>{String(o.filled_qty ?? '0')}</td>
                    <td>{o.filled_avg_price ? fmt(o.filled_avg_price) : fmt(o.limit_price)}</td>
                    <td>
                      <span className={`pill ${
                        status === 'filled'    ? 'pill-green' :
                        status === 'canceled'  ? 'pill-gray'  :
                        status === 'rejected'  ? 'pill-red'   :
                        'pill-amber'
                      }`}>
                        {status}
                      </span>
                    </td>
                    <td style={{ color: '#6B7280', fontSize: 11 }}>
                      {o.submitted_at ? new Date(String(o.submitted_at)).toLocaleString() : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Section>
    </div>
  )
}

function Section({
  title,
  icon,
  count,
  children,
  style,
}: {
  title: string
  icon: React.ReactNode
  count?: number
  children: React.ReactNode
  style?: React.CSSProperties
}) {
  return (
    <div className="card" style={{ overflow: 'hidden', ...style }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '14px 16px',
          borderBottom: '1px solid #1A1F2E',
        }}
      >
        <span style={{ color: '#0ECFB3' }}>{icon}</span>
        <span style={{ fontFamily: 'Syne', fontWeight: 600, fontSize: 13, color: '#E8EAF0' }}>
          {title}
        </span>
        {count !== undefined && (
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
            {count}
          </span>
        )}
      </div>
      <div style={{ overflowX: 'auto' }}>{children}</div>
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
      <div className="card" style={{ padding: 24, display: 'flex', alignItems: 'center', gap: 12, maxWidth: 480 }}>
        <AlertCircle size={18} color="#F04D4D" />
        <span style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: '#F04D4D' }}>{msg}</span>
      </div>
    </div>
  )
}

function Empty({ msg }: { msg: string }) {
  return (
    <div style={{ padding: '32px 16px', textAlign: 'center', fontFamily: 'JetBrains Mono', fontSize: 12, color: '#2A2F3E' }}>
      {msg}
    </div>
  )
}

export { PageLoader, PageError, Section, Empty, fmt, fmtPct }
