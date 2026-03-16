import { useEffect, useState } from 'react'
import { ClipboardList, Plus, X, AlertCircle } from 'lucide-react'
import { getOrders, placeOrder, cancelOrder } from '../api/client'

type Order = Record<string, unknown>

function fmt(v: unknown) {
  const n = parseFloat(String(v ?? 0))
  return isNaN(n) ? '—' : `$${n.toFixed(2)}`
}

const ORDER_TYPES  = ['market', 'limit', 'stop', 'stop_limit']
const TIME_IN_FORCE = ['day', 'gtc', 'ioc', 'fok']

export default function Orders() {
  const [orders, setOrders]     = useState<Order[]>([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState('all')
  const [showForm, setShowForm] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [cancelingId, setCancelingId] = useState<string | null>(null)

  // Form state
  const [form, setForm] = useState({
    symbol: '',
    qty: '',
    side: 'buy',
    type: 'market',
    time_in_force: 'day',
    limit_price: '',
    stop_price: '',
  })

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const status = statusFilter === 'all' ? undefined : statusFilter
      setOrders(await getOrders(status))
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [statusFilter]) // eslint-disable-line

  const handlePlace = async () => {
    setFormError(null)
    if (!form.symbol || !form.qty) {
      setFormError('Symbol and quantity are required')
      return
    }
    const data: Record<string, unknown> = {
      symbol: form.symbol.toUpperCase(),
      qty: form.qty,
      side: form.side,
      type: form.type,
      time_in_force: form.time_in_force,
    }
    if (form.type === 'limit' || form.type === 'stop_limit') {
      if (!form.limit_price) { setFormError('Limit price required'); return }
      data.limit_price = form.limit_price
    }
    if (form.type === 'stop' || form.type === 'stop_limit') {
      if (!form.stop_price) { setFormError('Stop price required'); return }
      data.stop_price = form.stop_price
    }
    setSubmitting(true)
    try {
      await placeOrder(data)
      setShowForm(false)
      setForm({ symbol: '', qty: '', side: 'buy', type: 'market', time_in_force: 'day', limit_price: '', stop_price: '' })
      await load()
    } catch (e) {
      setFormError(String(e))
    } finally {
      setSubmitting(false)
    }
  }

  const handleCancel = async (id: string) => {
    setCancelingId(id)
    try {
      await cancelOrder(id)
      await load()
    } catch (e) {
      setError(String(e))
    } finally {
      setCancelingId(null)
    }
  }

  return (
    <div style={{ padding: '28px 32px', maxWidth: 1200 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontFamily: 'Syne', fontSize: 22, fontWeight: 800, color: '#E8EAF0', margin: 0 }}>
            Orders
          </h1>
          <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: '#6B7280', marginTop: 4 }}>
            Order history and management
          </p>
        </div>
        <button className="btn btn-teal" onClick={() => setShowForm(!showForm)}>
          <Plus size={14} />
          Place Order
        </button>
      </div>

      {/* Place order form */}
      {showForm && (
        <div className="card" style={{ padding: '20px 24px', marginBottom: 20, borderColor: 'rgba(14,207,179,0.2)' }}>
          <div style={{ fontFamily: 'Syne', fontWeight: 600, fontSize: 14, color: '#E8EAF0', marginBottom: 16 }}>
            New Order
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 16 }}>
            <Field label="Symbol">
              <input
                className="field"
                placeholder="AAPL"
                value={form.symbol}
                onChange={e => setForm(f => ({ ...f, symbol: e.target.value.toUpperCase() }))}
              />
            </Field>
            <Field label="Qty">
              <input
                className="field"
                type="number"
                min="1"
                placeholder="1"
                value={form.qty}
                onChange={e => setForm(f => ({ ...f, qty: e.target.value }))}
              />
            </Field>
            <Field label="Side">
              <Select value={form.side} onChange={v => setForm(f => ({ ...f, side: v }))} options={['buy', 'sell']} />
            </Field>
            <Field label="Order Type">
              <Select value={form.type} onChange={v => setForm(f => ({ ...f, type: v }))} options={ORDER_TYPES} />
            </Field>
            <Field label="Time in Force">
              <Select value={form.time_in_force} onChange={v => setForm(f => ({ ...f, time_in_force: v }))} options={TIME_IN_FORCE} />
            </Field>
            {(form.type === 'limit' || form.type === 'stop_limit') && (
              <Field label="Limit Price">
                <input
                  className="field"
                  type="number"
                  step="0.01"
                  placeholder="0.00"
                  value={form.limit_price}
                  onChange={e => setForm(f => ({ ...f, limit_price: e.target.value }))}
                />
              </Field>
            )}
            {(form.type === 'stop' || form.type === 'stop_limit') && (
              <Field label="Stop Price">
                <input
                  className="field"
                  type="number"
                  step="0.01"
                  placeholder="0.00"
                  value={form.stop_price}
                  onChange={e => setForm(f => ({ ...f, stop_price: e.target.value }))}
                />
              </Field>
            )}
          </div>
          {formError && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
              <AlertCircle size={14} color="#F04D4D" />
              <span style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: '#F04D4D' }}>{formError}</span>
            </div>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-teal" onClick={handlePlace} disabled={submitting}>
              {submitting ? 'Placing…' : `Place ${form.side.toUpperCase()} Order`}
            </button>
            <button className="btn btn-outline" onClick={() => { setShowForm(false); setFormError(null) }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Filter tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {['all', 'open', 'filled', 'canceled'].map(s => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              fontFamily: 'JetBrains Mono',
              fontSize: 11,
              fontWeight: 600,
              cursor: 'pointer',
              border: `1px solid ${statusFilter === s ? '#0ECFB3' : '#1A1F2E'}`,
              background: statusFilter === s ? 'rgba(14,207,179,0.1)' : 'transparent',
              color: statusFilter === s ? '#0ECFB3' : '#6B7280',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
            }}
          >
            {s}
          </button>
        ))}
      </div>

      {error && (
        <div className="card" style={{ padding: '14px 16px', marginBottom: 16, display: 'flex', gap: 10, alignItems: 'center', borderColor: 'rgba(240,77,77,0.3)' }}>
          <AlertCircle size={16} color="#F04D4D" />
          <span style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: '#F04D4D' }}>{error}</span>
        </div>
      )}

      <div className="card" style={{ overflow: 'hidden' }}>
        <div style={{ padding: '14px 16px', borderBottom: '1px solid #1A1F2E', display: 'flex', alignItems: 'center', gap: 8 }}>
          <ClipboardList size={14} color="#0ECFB3" />
          <span style={{ fontFamily: 'Syne', fontWeight: 600, fontSize: 13, color: '#E8EAF0' }}>
            Order History
          </span>
          {loading && (
            <span style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: '#6B7280', marginLeft: 'auto' }}>
              Loading…
            </span>
          )}
        </div>

        {orders.length === 0 && !loading ? (
          <div style={{ padding: '48px 16px', textAlign: 'center', fontFamily: 'JetBrains Mono', fontSize: 12, color: '#2A2F3E' }}>
            No orders found
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Type</th>
                  <th>Qty</th>
                  <th>Filled</th>
                  <th>Limit</th>
                  <th>Stop</th>
                  <th>Fill Price</th>
                  <th>Status</th>
                  <th>TIF</th>
                  <th>Submitted</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o, i) => {
                  const side   = String(o.side ?? '')
                  const status = String(o.status ?? '')
                  const canCancel = status === 'new' || status === 'accepted' || status === 'pending_new'
                  const id = String(o.id ?? '')
                  return (
                    <tr key={i}>
                      <td style={{ color: '#0ECFB3', fontWeight: 600 }}>{String(o.symbol ?? '—')}</td>
                      <td className={side === 'buy' ? 'pos' : 'neg'} style={{ fontWeight: 600 }}>
                        {side.toUpperCase()}
                      </td>
                      <td style={{ color: '#6B7280' }}>{String(o.type ?? '—')}</td>
                      <td>{String(o.qty ?? '—')}</td>
                      <td style={{ color: '#6B7280' }}>{String(o.filled_qty ?? '0')}</td>
                      <td>{o.limit_price ? fmt(o.limit_price) : '—'}</td>
                      <td>{o.stop_price ? fmt(o.stop_price) : '—'}</td>
                      <td style={{ fontWeight: 600 }}>{o.filled_avg_price ? fmt(o.filled_avg_price) : '—'}</td>
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
                      <td style={{ color: '#6B7280' }}>{String(o.time_in_force ?? '—')}</td>
                      <td style={{ color: '#6B7280', fontSize: 11 }}>
                        {o.submitted_at ? new Date(String(o.submitted_at)).toLocaleString() : '—'}
                      </td>
                      <td>
                        {canCancel && (
                          <button
                            className="btn btn-red"
                            style={{ padding: '3px 8px', fontSize: 11 }}
                            onClick={() => handleCancel(id)}
                            disabled={cancelingId === id}
                          >
                            <X size={11} />
                            {cancelingId === id ? '…' : 'Cancel'}
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontFamily: 'Syne', fontSize: 10, color: '#6B7280', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 6 }}>
        {label}
      </div>
      {children}
    </div>
  )
}

function Select({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <select
      className="field"
      value={value}
      onChange={e => onChange(e.target.value)}
      style={{ cursor: 'pointer' }}
    >
      {options.map(o => (
        <option key={o} value={o}>{o}</option>
      ))}
    </select>
  )
}
