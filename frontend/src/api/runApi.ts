import { getAuthToken } from './auth-token'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''

function apiUrl(path: string): string {
  return `${API_BASE.replace(/\/$/, '')}${path}`
}

function authHeaders(): Record<string, string> {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function jsonRequest<T>(
  path: string,
  init: RequestInit,
  fetchImpl: typeof fetch,
): Promise<T> {
  const response = await fetchImpl(apiUrl(path), init)
  if (!response.ok) throw new Error(`${init.method ?? 'GET'} ${path} failed: ${response.status}`)
  return response.json() as Promise<T>
}

export type RunStatus =
  | 'queued'
  | 'assigned'
  | 'running'
  | 'waiting_approval'
  | 'waiting_input'
  | 'cancel_requested'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface RunResponse {
  id: string
  tenant_id: string
  session_id: string
  created_by_user_id: string
  run_type: 'chat'
  status: RunStatus
  replaces_run_id: string | null
  retry_count: number
  created_at: string
  queued_at: string
  finished_at: string | null
  error_code: string | null
  error_message: string | null
}

export interface CreateRunBody {
  session_id: string | null
  prompt: string
  replaces_run_id?: string | null
}

export interface TenantSummary {
  id: string
  name: string
  is_personal: boolean
  role: 'owner' | 'admin' | 'member'
}

export interface RunSessionSummary {
  id: string
  tenant_id: string
  created_by_user_id: string
  title: string | null
  created_at: string
  updated_at: string
  archived_at: string | null
}

export interface DurableRunMessage {
  id: string
  role: 'user' | 'assistant' | 'tool' | 'system'
  content: string
  status: string
  created_at: string
}

export interface RunSessionDetail extends RunSessionSummary {
  messages: DurableRunMessage[]
  has_more: boolean
  active_run_id: string | null
  active_run_status: RunStatus | null
  active_pause_type: 'approval' | 'input' | null
  active_pause_request: Record<string, unknown> | null
}

export function createRun(
  tenantId: string,
  body: CreateRunBody,
  idempotencyKey: string,
  fetchImpl: typeof fetch = fetch,
  signal?: AbortSignal,
): Promise<RunResponse> {
  return jsonRequest(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/runs`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
        ...authHeaders(),
      },
      body: JSON.stringify(body),
      signal,
    },
    fetchImpl,
  )
}

export function getRun(
  tenantId: string,
  runId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<RunResponse> {
  return jsonRequest(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/runs/${encodeURIComponent(runId)}`,
    { headers: authHeaders() },
    fetchImpl,
  )
}

export function cancelRun(
  tenantId: string,
  runId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<RunResponse> {
  return jsonRequest(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/runs/${encodeURIComponent(runId)}/cancel`,
    { method: 'POST', headers: authHeaders() },
    fetchImpl,
  )
}

export function resumeRun(
  tenantId: string,
  runId: string,
  response: Record<string, unknown>,
  fetchImpl: typeof fetch = fetch,
): Promise<RunResponse> {
  return jsonRequest(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/runs/${encodeURIComponent(runId)}/resume`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ response }),
    },
    fetchImpl,
  )
}

export interface RunEventFetchOptions {
  lastEventId?: string | null
  signal?: AbortSignal
  fetchImpl?: typeof fetch
}

export async function fetchRunEvents(
  tenantId: string,
  runId: string,
  options: RunEventFetchOptions = {},
): Promise<Response> {
  const headers: Record<string, string> = {
    Accept: 'text/event-stream',
    ...authHeaders(),
  }
  if (options.lastEventId) headers['Last-Event-ID'] = options.lastEventId
  const response = await (options.fetchImpl ?? fetch)(
    apiUrl(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/runs/${encodeURIComponent(runId)}/events`,
    ),
    { headers, signal: options.signal },
  )
  if (!response.ok) throw new Error(`GET Run events failed: ${response.status}`)
  return response
}

export function listTenants(fetchImpl: typeof fetch = fetch): Promise<TenantSummary[]> {
  return jsonRequest('/api/v1/tenants', { headers: authHeaders() }, fetchImpl)
}

export function listRunSessions(
  tenantId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<RunSessionSummary[]> {
  return jsonRequest(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/sessions`,
    { headers: authHeaders() },
    fetchImpl,
  )
}

export function getRunSession(
  tenantId: string,
  sessionId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<RunSessionDetail> {
  return jsonRequest(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/sessions/${encodeURIComponent(sessionId)}?limit=1000`,
    { headers: authHeaders() },
    fetchImpl,
  )
}

export function renameRunSession(
  tenantId: string,
  sessionId: string,
  title: string,
  fetchImpl: typeof fetch = fetch,
): Promise<RunSessionSummary> {
  return jsonRequest(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/sessions/${encodeURIComponent(sessionId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ title }),
    },
    fetchImpl,
  )
}

export async function archiveRunSession(
  tenantId: string,
  sessionId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  const path = `/api/v1/tenants/${encodeURIComponent(tenantId)}/sessions/${encodeURIComponent(sessionId)}`
  const response = await fetchImpl(apiUrl(path), {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!response.ok && response.status !== 204) {
    throw new Error(`DELETE ${path} failed: ${response.status}`)
  }
}
