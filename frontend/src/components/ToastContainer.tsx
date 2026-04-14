import { useEffect } from 'react'
import { useToast, ToastMessage } from '../hooks/useToast'

const BORDER_COLORS: Record<ToastMessage['type'], string> = {
  error: '#F04D4D',
  success: '#22C55E',
  info: '#0ECFB3',
}

function Toast({ toast }: { toast: ToastMessage }) {
  const { dismissToast } = useToast()

  useEffect(() => {
    const timer = setTimeout(() => dismissToast(toast.id), 4000)
    return () => clearTimeout(timer)
  }, [toast.id, dismissToast])

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
        maxWidth: 320,
        background: '#0D111C',
        border: '1px solid #1A1F2E',
        borderLeft: `4px solid ${BORDER_COLORS[toast.type]}`,
        borderRadius: 6,
        padding: '10px 12px',
        fontFamily: 'JetBrains Mono',
        fontSize: 12,
        color: '#E8EAF0',
        boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
        marginTop: 8,
      }}
    >
      <span style={{ flex: 1, wordBreak: 'break-word' }}>{toast.message}</span>
      <button
        onClick={() => dismissToast(toast.id)}
        style={{
          background: 'none',
          border: 'none',
          color: '#6B7280',
          cursor: 'pointer',
          fontFamily: 'JetBrains Mono',
          fontSize: 12,
          padding: 0,
          lineHeight: 1,
          flexShrink: 0,
        }}
        aria-label="Dismiss"
      >
        ✕
      </button>
    </div>
  )
}

export default function ToastContainer() {
  const { toasts } = useToast()

  if (toasts.length === 0) return null

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 24,
        right: 24,
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-end',
      }}
    >
      {toasts.map(t => (
        <Toast key={t.id} toast={t} />
      ))}
    </div>
  )
}
