import { getAuthToken } from './auth-token'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''
const BASE = '/api/v0/persona'

// trailing-slash 安全: VITE_API_BASE 可能写成 "http://x/" 也可能不带, 跟 memoryApi.ts 对齐
const apiUrl = (path: string) => `${API_BASE.replace(/\/$/, '')}${path}`

export type PersonaSource = 'user' | 'agent'

export interface PersonaItem {
  id: string
  text: string
  source: PersonaSource
  position: number
  created_at: string
  updated_at: string
}

export interface PersonaListResponse {
  user_declared: PersonaItem[]
  agent_inferred: PersonaItem[]
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAuthToken()
  const res = await fetch(apiUrl(path), {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers as Record<string, string> ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`)
  }
  if (res.status === 204) {
    return undefined as T
  }
  return (await res.json()) as T
}

export async function fetchPersona(): Promise<PersonaListResponse> {
  return fetchJson<PersonaListResponse>(BASE)
}

export async function addPersonaItem(params: {
  text: string
  target_section: PersonaSource
}): Promise<PersonaItem> {
  return fetchJson<PersonaItem>(`${BASE}/items`, {
    method: 'POST',
    body: JSON.stringify(params),
  })
}

export async function updatePersonaItem(
  itemId: string,
  text: string
): Promise<PersonaItem> {
  return fetchJson<PersonaItem>(`${BASE}/items/${itemId}`, {
    method: 'PATCH',
    body: JSON.stringify({ text }),
  })
}

export async function deletePersonaItem(itemId: string): Promise<void> {
  await fetchJson<void>(`${BASE}/items/${itemId}`, { method: 'DELETE' })
}
