// C.5 cross-session memory — typed API client (Plan 7A)
//
// 契约 § 10 5 endpoint:
//   GET  /api/v0/memory/graph
//   GET  /api/v0/memory/timeline
//   GET  /api/v0/memory/audit
//   POST /api/v0/memory/edges/{id}/invalidate
//   GET  /api/v0/memory/blocks

import type {
  AuditResponse,
  BlocksResponse,
  GraphResponse,
  InvalidateResponse,
  TimelineFilters,
  TimelineResponse,
} from '@/types/memory'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''
const BASE = '/api/v0/memory'

function apiUrl(path: string): string {
  const root = (API_BASE ?? '').replace(/\/$/, '')
  return `${root}${path}`
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), init)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`)
  }
  return (await res.json()) as T
}

export async function fetchMemoryGraph(): Promise<GraphResponse> {
  return fetchJson<GraphResponse>(`${BASE}/graph`)
}

export async function fetchMemoryTimeline(
  filters: TimelineFilters = {},
): Promise<TimelineResponse> {
  const sp = new URLSearchParams()
  if (filters.rel_type) sp.set('rel_type', filters.rel_type)
  if (filters.entity_label) sp.set('entity_label', filters.entity_label)
  if (filters.page) sp.set('page', String(filters.page))
  if (filters.page_size) sp.set('page_size', String(filters.page_size))
  const qs = sp.toString()
  return fetchJson<TimelineResponse>(
    `${BASE}/timeline${qs ? `?${qs}` : ''}`,
  )
}

export async function fetchMemoryAudit(): Promise<AuditResponse> {
  return fetchJson<AuditResponse>(`${BASE}/audit`)
}

export async function fetchMemoryBlocks(): Promise<BlocksResponse> {
  return fetchJson<BlocksResponse>(`${BASE}/blocks`)
}

export async function invalidateMemoryEdge(
  edgeId: string,
): Promise<InvalidateResponse> {
  return fetchJson<InvalidateResponse>(
    `${BASE}/edges/${encodeURIComponent(edgeId)}/invalidate`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' } },
  )
}
