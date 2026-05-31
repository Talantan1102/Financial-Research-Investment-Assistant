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
import { getAuthToken } from './auth-token' // C66: SSOT auth header for bare-fetch callers

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''

function apiUrl(path: string): string {
  const base = (API_BASE ?? '').replace(/\/$/, '')
  return `${base}${path}`
}

// C66: shared helper — mirrors monitoring.ts authHeader() pattern
function getAuthHeaders(): Record<string, string> {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function listChats(): Promise<ChatSession[]> {
  const res = await fetch(apiUrl('/api/v0/chats'), {
    headers: { ...getAuthHeaders() },
  })
  if (!res.ok) throw new Error(`listChats failed: ${res.status}`)
  return res.json() as Promise<ChatSession[]>
}

export async function createChat(
  req: CreateChatRequest = {},
): Promise<ChatSession> {
  const res = await fetch(apiUrl('/api/v0/chats'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new Error(`createChat failed: ${res.status}`)
  return res.json() as Promise<ChatSession>
}

export async function getChat(id: string): Promise<ChatDetail> {
  const res = await fetch(apiUrl(`/api/v0/chats/${encodeURIComponent(id)}`), {
    headers: { ...getAuthHeaders() },
  })
  if (!res.ok) throw new Error(`getChat failed: ${res.status}`)
  return res.json() as Promise<ChatDetail>
}

export async function deleteChat(id: string): Promise<void> {
  const res = await fetch(apiUrl(`/api/v0/chats/${encodeURIComponent(id)}`), {
    method: 'DELETE',
    headers: { ...getAuthHeaders() },
  })
  if (!res.ok && res.status !== 204) {
    throw new Error(`deleteChat failed: ${res.status}`)
  }
}

export function buildChatPostUrl(): string {
  return apiUrl('/api/v0/chat')
}

export interface ChatPostJsonResponse {
  task_id: string
  session_id: string
  stream_url: string
}

/**
 * Plan 2: GET /api/v0/chat/stream/{task_id}?last_event_id=X URL builder.
 *
 * 用于前端 useChatSSE 在收到 POST /chat 的 JSON 响应后,打开 Redis Streams
 * replay 端点。`last_event_id` 是 Redis Stream entry id (`<ms>-<seq>`),
 * 断流后回传给服务端 XREAD STREAMS key {last_id} 续读。首次连接传 '0' 拿全量。
 */
export function buildChatTaskStreamUrl(
  taskId: string,
  lastEventId: string = '0',
): string {
  return apiUrl(
    `/api/v0/chat/stream/${encodeURIComponent(taskId)}?last_event_id=${encodeURIComponent(lastEventId)}`,
  )
}

/**
 * @deprecated Plan 1 — frontend no longer uses this. Backend endpoint
 *   GET /api/v0/chat/stream/:id (sessionId variant) was never implemented;
 *   Plan 2 uses `buildChatTaskStreamUrl(taskId)` instead.
 *   Kept exported only because `chatApi.test.ts` still asserts its URL shape.
 */
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

/**
 * Plan 3 Task 4: POST /api/v0/chat/cancel/{task_id} — async cancel signal。
 * 服务端 publish 到 Redis pub/sub channel,worker 内 listener 接到 → graph
 * 节点之间检查 flag → raise GraphInterrupt → finalize 走 partial commit。
 * 立即返 202,不等 worker 反应。
 */
export async function cancelChatTask(taskId: string): Promise<void> {
  const res = await fetch(
    apiUrl(`/api/v0/chat/cancel/${encodeURIComponent(taskId)}`),
    { method: 'POST', headers: { ...getAuthHeaders() } },
  )
  if (!res.ok && res.status !== 202) {
    throw new Error(`cancel failed: ${res.status}`)
  }
}

export interface RetryChatResponse {
  task_id: string
  parent_task_id: string
  stream_url: string
  resumed_from_checkpoint: string
}

/**
 * Plan 3 Task 5: POST /api/v0/chat/retry/{task_id} — resume from checkpoint。
 * 后端从 chat_tasks.langgraph_checkpoint_id 创建新 task(parent_task_id 链),
 * 返回新 task_id + stream_url。前端拿到后立刻打开 stream 接续。
 */
export async function retryChatTask(taskId: string): Promise<RetryChatResponse> {
  const res = await fetch(
    apiUrl(`/api/v0/chat/retry/${encodeURIComponent(taskId)}`),
    { method: 'POST', headers: { ...getAuthHeaders() } },
  )
  if (!res.ok) {
    throw new Error(`retry failed: ${res.status}`)
  }
  return (await res.json()) as RetryChatResponse
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
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(args),
  })
  if (!res.ok) throw new Error(`escalate failed: ${res.status}`)
  return { ok: true }
}

/** 重命名 session — PUT /api/sessions/:id (2026-05-17) */
export async function renameChat(id: string, title: string): Promise<void> {
  const resp = await fetch(apiUrl(`/api/v0/chats/${encodeURIComponent(id)}`), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ title }),
  })
  if (!resp.ok) {
    throw new Error(`renameChat failed: ${resp.status}`)
  }
}

export type { CreateChatRequest, SendChatMessageRequest }
