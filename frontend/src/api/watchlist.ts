export interface WatchlistItem { id: string; ts_code: string; name: string; note: string | null; monitoring_enabled: boolean }
const base = '/api/v0/watchlist'
async function json<T>(path: string, init?: RequestInit): Promise<T> { const r = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) } }); if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.status === 204 ? undefined as T : await r.json() as T }
export const listWatchlist = () => json<WatchlistItem[]>(base)
export const addWatchlist = (payload: Omit<WatchlistItem, 'id'>) => json<WatchlistItem>(base, { method: 'POST', body: JSON.stringify(payload) })
export const updateWatchlist = (tsCode: string, changes: Partial<Omit<WatchlistItem, 'id' | 'ts_code'>>) => json<WatchlistItem>(`${base}/${encodeURIComponent(tsCode)}`, { method: 'PATCH', body: JSON.stringify(changes) })
export const removeWatchlist = (tsCode: string) => json<void>(`${base}/${encodeURIComponent(tsCode)}`, { method: 'DELETE' })
