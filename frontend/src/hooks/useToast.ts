import { createContext, useContext, useState, useCallback, ReactNode, createElement } from 'react'

export type ToastMessage = {
  id: string
  message: string
  type: 'error' | 'success' | 'info'
}

type ToastContextValue = {
  toasts: ToastMessage[]
  addToast: (msg: string, type?: ToastMessage['type']) => void
  dismissToast: (id: string) => void
}

export const ToastContext = createContext<ToastContextValue>({
  toasts: [],
  addToast: () => {},
  dismissToast: () => {},
})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([])

  const addToast = useCallback((msg: string, type: ToastMessage['type'] = 'info') => {
    const id = String(Date.now())
    setToasts(prev => [...prev, { id, message: msg, type }])
  }, [])

  const dismissToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  return createElement(ToastContext.Provider, { value: { toasts, addToast, dismissToast } }, children)
}

export function useToast(): ToastContextValue {
  return useContext(ToastContext)
}
