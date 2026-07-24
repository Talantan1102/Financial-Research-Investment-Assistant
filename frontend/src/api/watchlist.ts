import { getAuthToken } from './auth-token'

const API_BASE = ((import.meta.env.VITE_API_BASE as string) ?? '').replace(
  /\/$/,
  '',
)
const WATCHLIST_PATH = '/api/v0/watchlist'

export interface WatchlistItem {
  id: string
  ts_code: string
  name: string
  note: string | null
  monitoring_enabled: boolean
}

export interface WatchlistCreate {
  ts_code: string
  name: string
  note?: string | null
  monitoring_enabled?: boolean
}

export interface WatchlistUpdate {
  name?: string
  note?: string | null
  monitoring_enabled?: boolean
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAuthToken()
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: string | { message?: string }
    } | null
    const detail = body?.detail
    throw new Error(
      typeof detail === 'string'
        ? detail
        : (detail?.message ?? `自选股操作失败（${response.status}）`),
    )
  }
  return response.json() as Promise<T>
}

export function listWatchlist(): Promise<WatchlistItem[]> {
  return requestJson(WATCHLIST_PATH)
}

export function addWatchlistItem(
  payload: WatchlistCreate,
): Promise<WatchlistItem> {
  return requestJson(WATCHLIST_PATH, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateWatchlistItem(
  tsCode: string,
  changes: WatchlistUpdate,
): Promise<WatchlistItem> {
  return requestJson(`${WATCHLIST_PATH}/${encodeURIComponent(tsCode)}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}

export function removeWatchlistItem(
  tsCode: string,
): Promise<{ removed: boolean }> {
  return requestJson(`${WATCHLIST_PATH}/${encodeURIComponent(tsCode)}`, {
    method: 'DELETE',
  })
}
