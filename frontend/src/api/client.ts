const BASE = '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${msg}`)
  }
  return res.json()
}

export const getAccount = () =>
  request<Record<string, unknown>>('/account')

export const getPositions = () =>
  request<Record<string, unknown>[]>('/positions')

export const getOrders = (status?: string) =>
  request<Record<string, unknown>[]>(`/orders${status ? `?status=${status}` : ''}`)

export const getChain = (symbol: string) =>
  request<Record<string, unknown>>(`/options/chain/${symbol}`)

export const placeOrder = (data: Record<string, unknown>) =>
  request<Record<string, unknown>>('/orders', {
    method: 'POST',
    body: JSON.stringify(data),
  })

export const cancelOrder = (id: string) =>
  request<Record<string, unknown>>(`/orders/${id}`, { method: 'DELETE' })

export const getWatchlist = () =>
  request<Record<string, unknown>[]>('/watchlist')

export const addToWatchlist = (symbol: string) =>
  request<Record<string, unknown>>('/watchlist', {
    method: 'POST',
    body: JSON.stringify({ symbol }),
  })

export const removeFromWatchlist = (symbol: string) =>
  request<Record<string, unknown>>(`/watchlist/${symbol}`, { method: 'DELETE' })
