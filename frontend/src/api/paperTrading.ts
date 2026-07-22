import type {
  CancelConfirmRequest,
  CancelPreview,
  OrderConfirmRequest,
  OrderDraft,
  OrderPreview,
  PaperAccount,
  PaperOrder,
  ResetConfirmRequest,
  ResetPreview,
  ResetPreviewRequest,
} from '@/types/paper-trading'
import { getAuthToken } from './auth-token'

const API_BASE = ((import.meta.env.VITE_API_BASE as string) ?? '').replace(/\/$/, '')
const BASE = '/api/v0/paper-trading'

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAuthToken()
  const headers = {
    ...(init?.headers as Record<string, string> ?? {}),
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`HTTP ${response.status}: ${detail || response.statusText}`)
  }
  return (await response.json()) as T
}

export const getAccount = () => fetchJson<PaperAccount>(`${BASE}/account`)
export const listOrders = () => fetchJson<PaperOrder[]>(`${BASE}/orders`)
export const getOrder = (orderId: string) =>
  fetchJson<PaperOrder>(`${BASE}/orders/${encodeURIComponent(orderId)}`)

export const previewOrder = (orderId: string, draft: OrderDraft) =>
  fetchJson<OrderPreview>(`${BASE}/orders/${encodeURIComponent(orderId)}/preview`, {
    method: 'POST',
    body: JSON.stringify({ draft }),
  })

export const confirmOrder = (orderId: string, payload: OrderConfirmRequest) =>
  fetchJson<PaperOrder>(`${BASE}/orders/${encodeURIComponent(orderId)}/confirm`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const previewCancel = (orderId: string) =>
  fetchJson<CancelPreview>(`${BASE}/orders/${encodeURIComponent(orderId)}/cancel-preview`, {
    method: 'POST',
  })

export const confirmCancel = (orderId: string, payload: CancelConfirmRequest) =>
  fetchJson<PaperOrder>(`${BASE}/orders/${encodeURIComponent(orderId)}/cancel-confirm`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const previewReset = (payload: ResetPreviewRequest) =>
  fetchJson<ResetPreview>(`${BASE}/account/reset-preview`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const confirmReset = (payload: ResetConfirmRequest) =>
  fetchJson<PaperAccount>(`${BASE}/account/reset-confirm`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
