/**
 * frontend/src/api/chatApi.ts
 *
 * REST client + URL builders for v0.9 chat endpoints. SSE consumption lives
 * in `useChatSSE` (fetch + ReadableStream); this file only:
 *   - exposes typed REST CRUD for /api/v0/chats
 *   - exposes URL builders for SSE endpoints (so the hook stays free of base-URL plumbing)
 *   - exposes the `escalate` POST URL builder as a stub for Plan 3
 */

import type {
  ChatDetail,
  ChatSession,
  CreateChatRequest,
  SendChatMessageRequest,
} from '@/types/chat'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''

function apiUrl(path: string): string {
  const base = (API_BASE ?? '').replace(/\/$/, '')
  return `${base}${path}`
}

export async function listChats(): Promise<ChatSession[]> {
  const res = await fetch(apiUrl('/api/v0/chats'))
  if (!res.ok) throw new Error(`listChats failed: ${res.status}`)
  return res.json() as Promise<ChatSession[]>
}

export async function createChat(
  req: CreateChatRequest = {},
): Promise<ChatSession> {
  const res = await fetch(apiUrl('/api/v0/chats'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new Error(`createChat failed: ${res.status}`)
  return res.json() as Promise<ChatSession>
}

export async function getChat(id: string): Promise<ChatDetail> {
  const res = await fetch(apiUrl(`/api/v0/chats/${encodeURIComponent(id)}`))
  if (!res.ok) throw new Error(`getChat failed: ${res.status}`)
  return res.json() as Promise<ChatDetail>
}

export async function deleteChat(id: string): Promise<void> {
  const res = await fetch(apiUrl(`/api/v0/chats/${encodeURIComponent(id)}`), {
    method: 'DELETE',
  })
  if (!res.ok && res.status !== 204) {
    throw new Error(`deleteChat failed: ${res.status}`)
  }
}

export function buildChatPostUrl(): string {
  return apiUrl('/api/v0/chat')
}

export function buildChatStreamUrl(
  sessionId: string,
  lastEventId?: number,
): string {
  const base = apiUrl(`/api/v0/chat/stream/${encodeURIComponent(sessionId)}`)
  if (lastEventId === undefined || lastEventId === null) return base
  const sep = base.includes('?') ? '&' : '?'
  return `${base}${sep}last_event_id=${lastEventId}`
}

export function buildEscalateUrl(): string {
  return apiUrl('/api/v0/chat/escalate')
}

import type { EscalationPacket } from '@/types/escalation'

export interface ConfirmEscalationArgs {
  session_id: string
  packet: EscalationPacket
}

export interface ConfirmEscalationResult {
  ok: true
  record_id?: string
}

export async function confirmEscalation(
  args: ConfirmEscalationArgs,
): Promise<ConfirmEscalationResult> {
  const res = await fetch(buildEscalateUrl(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args),
  })
  if (!res.ok) throw new Error(`escalate failed: ${res.status}`)
  return { ok: true }
}

export type { CreateChatRequest, SendChatMessageRequest }
