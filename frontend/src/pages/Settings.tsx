import { useEffect, useState } from 'react'
import { Plus, X, Settings as SettingsIcon, AlertCircle, Check } from 'lucide-react'
import { getWatchlist, addToWatchlist, removeFromWatchlist } from '../api/client'

type WatchItem = Record<string, unknown>

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontFamily: 'Syne', fontSize: 11, color: '#E8EAF0', fontWeight: 600, marginBottom: 4 }}>
        {label}
      </div>
      {children}
      {hint && (
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: '#6B7280', marginTop: 4 }}>
          {hint}
        </div>
      )}
    </div>
  )
}

export default function Settings() {
  const [watchlist, setWatchlist] = useState<WatchItem[]>([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState<string | null>(null)
  const [newSymbol, setNewSymbol] = useState('')
  const [adding, setAdding]       = useState(false)
  const [addError, setAddError]   = useState<string | null>(null)
  const [removingId, setRemovingId] = useState<string | null>(null)
  const [saved, setSaved]         = useState(false)

  // BB params
  const [bbParams, setBbParams] = useState({
    period: '20',
    std_dev: '2.0',
    lookback: '5',
    macd_fast: '12',
    macd_slow: '26',
    macd_signal: '9',
    stop_loss_pct: '2.0',
    take_profit_pct: '5.0',
  })

  const loadWatchlist = () =>
    getWatchlist()
      .then(w => setWatchlist(w))
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))

  useEffect(() => { loadWatchlist() }, [])

  const handleAdd = async () => {
    const s = newSymbol.trim().toUpperCase()
    if (!s) return
    setAdding(true)
    setAddError(null)
    try {
      await addToWatchlist(s)
      setNewSymbol('')
      await loadWatchlist()
    } catch (e) {
      setAddError(String(e))
    } finally {
      setAdding(false)
    }
  }

  const handleRemove = async (symbol: string) => {
    setRemovingId(symbol)
    try {
      await removeFromWatchlist(symbol)
      await loadWatchlist()
    } catch (e) {
      setError(String(e))
    } finally {
      setRemovingId(null)
    }
  }

  const handleSave = () => {
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div style={{ padding: '28px 32px', maxWidth: 900 }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontFamily: 'Syne', fontSize: 22, fontWeight: 800, color: '#E8EAF0', margin: 0 }}>
          Settings
        </h1>
        <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: '#6B7280', marginTop: 4 }}>
          Watchlist management and strategy parameters
        </p>
      </div>

      {error && (
        <div className="card" style={{ padding: '14px 16px', marginBottom: 16, display: 'flex', gap: 10, alignItems: 'center', borderColor: 'rgba(240,77,77,0.3)' }}>
          <AlertCircle size={16} color="#F04D4D" />
          <span style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: '#F04D4D' }}>{error}</span>
        </div>
      )}

      {/* Watchlist */}
      <div className="card" style={{ overflow: 'hidden', marginBottom: 16 }}>
        <div style={{ padding: '14px 16px', borderBottom: '1px solid #1A1F2E', display: 'flex', alignItems: 'center', gap: 8 }}>
          <SettingsIcon size={14} color="#0ECFB3" />
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
            {watchlist.length} symbols
          </span>
        </div>

        <div style={{ padding: '16px 20px' }}>
          {/* Add symbol */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
            <input
              className="field"
              style={{ maxWidth: 180 }}
              placeholder="Add symbol (e.g. TSLA)"
              value={newSymbol}
              onChange={e => setNewSymbol(e.target.value.toUpperCase())}
              onKeyDown={e => e.key === 'Enter' && handleAdd()}
            />
            <button className="btn btn-teal" onClick={handleAdd} disabled={adding || !newSymbol.trim()}>
              <Plus size={14} />
              {adding ? 'Adding…' : 'Add'}
            </button>
          </div>

          {addError && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
              <AlertCircle size={14} color="#F04D4D" />
              <span style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: '#F04D4D' }}>{addError}</span>
            </div>
          )}

          {loading ? (
            <div style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: '#6B7280' }}>Loading…</div>
          ) : watchlist.length === 0 ? (
            <div style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: '#2A2F3E', padding: '20px 0' }}>
              Watchlist is empty. Add symbols above.
            </div>
          ) : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {watchlist.map((item, i) => {
                const sym = String(item.symbol ?? item)
                return (
                  <div
                    key={i}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      background: '#0B0D11',
                      border: '1px solid #1A1F2E',
                      borderRadius: 6,
                      padding: '6px 10px',
                    }}
                  >
                    <span style={{ fontFamily: 'JetBrains Mono', fontSize: 12, fontWeight: 600, color: '#0ECFB3' }}>
                      {sym}
                    </span>
                    <button
                      onClick={() => handleRemove(sym)}
                      disabled={removingId === sym}
                      style={{
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        padding: 0,
                        display: 'flex',
                        alignItems: 'center',
                        color: '#6B7280',
                      }}
                    >
                      <X size={12} />
                    </button>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* BB Strategy Params */}
      <div className="card" style={{ overflow: 'hidden' }}>
        <div style={{ padding: '14px 16px', borderBottom: '1px solid #1A1F2E' }}>
          <span style={{ fontFamily: 'Syne', fontWeight: 600, fontSize: 13, color: '#E8EAF0' }}>
            BB Band Walk Parameters
          </span>
        </div>

        <div style={{ padding: '20px 24px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20 }}>
            <Field label="BB Period" hint="Bollinger Band period (bars)">
              <input
                className="field"
                type="number"
                value={bbParams.period}
                onChange={e => setBbParams(p => ({ ...p, period: e.target.value }))}
              />
            </Field>
            <Field label="Std Dev Multiplier" hint="Band width multiplier">
              <input
                className="field"
                type="number"
                step="0.1"
                value={bbParams.std_dev}
                onChange={e => setBbParams(p => ({ ...p, std_dev: e.target.value }))}
              />
            </Field>
            <Field label="Lookback Bars" hint="Walk confirmation bars">
              <input
                className="field"
                type="number"
                value={bbParams.lookback}
                onChange={e => setBbParams(p => ({ ...p, lookback: e.target.value }))}
              />
            </Field>
            <Field label="Stop Loss %" hint="Max loss per trade">
              <input
                className="field"
                type="number"
                step="0.1"
                value={bbParams.stop_loss_pct}
                onChange={e => setBbParams(p => ({ ...p, stop_loss_pct: e.target.value }))}
              />
            </Field>
          </div>

          <div style={{
            fontFamily: 'Syne',
            fontSize: 11,
            color: '#6B7280',
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
            marginBottom: 12,
          }}>
            MACD Settings
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
            <Field label="Fast Period" hint="MACD fast EMA">
              <input
                className="field"
                type="number"
                value={bbParams.macd_fast}
                onChange={e => setBbParams(p => ({ ...p, macd_fast: e.target.value }))}
              />
            </Field>
            <Field label="Slow Period" hint="MACD slow EMA">
              <input
                className="field"
                type="number"
                value={bbParams.macd_slow}
                onChange={e => setBbParams(p => ({ ...p, macd_slow: e.target.value }))}
              />
            </Field>
            <Field label="Signal Period" hint="MACD signal line">
              <input
                className="field"
                type="number"
                value={bbParams.macd_signal}
                onChange={e => setBbParams(p => ({ ...p, macd_signal: e.target.value }))}
              />
            </Field>
            <Field label="Take Profit %" hint="Target gain per trade">
              <input
                className="field"
                type="number"
                step="0.1"
                value={bbParams.take_profit_pct}
                onChange={e => setBbParams(p => ({ ...p, take_profit_pct: e.target.value }))}
              />
            </Field>
          </div>

          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <button className="btn btn-teal" onClick={handleSave}>
              {saved ? <Check size={14} /> : null}
              {saved ? 'Saved!' : 'Save Parameters'}
            </button>
            <span style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: '#6B7280' }}>
              Parameters are stored in memory until server restart
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
