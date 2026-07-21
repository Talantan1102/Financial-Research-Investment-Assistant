import { beforeEach, describe, expect, it } from 'vitest'
import { snapshot } from 'valtio'
import { http, HttpResponse } from 'msw'
import { chatSessionsActions, chatSessionsState } from '@/store/chat-sessions'
import { server } from '@/test-utils/msw-server'
import type { ChatSession } from '@/types/chat'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''
const now = '2026-05-09T00:00:00Z'
const session = (id: string, updatedAt = now): ChatSession => ({
  id, title: `chat ${id}`, created_at: now, updated_at: updatedAt,
  message_count: 0, last_msg_preview: null,
})
const tenantHandler = http.get(`${API_BASE}/api/v1/tenants`, () =>
  HttpResponse.json([
    { id: 'shared', name: 'shared', is_personal: false, role: 'member' },
    { id: 'personal', name: 'personal', is_personal: true, role: 'owner' },
  ]),
)

describe('chatSessionsStore v1', () => {
  beforeEach(() => chatSessionsActions.reset())

  it('sorts summaries by updated_at and upserts/removes locally', () => {
    chatSessionsActions.setSessions([
      session('a'), session('b', '2026-05-09T01:00:00Z'), session('c', '2026-05-08T00:00:00Z'),
    ])
    expect(snapshot(chatSessionsState).sessions.map((item) => item.id)).toEqual(['b', 'a', 'c'])
    chatSessionsActions.upsertSession(session('a', '2026-05-10T00:00:00Z'))
    expect(snapshot(chatSessionsState).sessions).toHaveLength(3)
    chatSessionsActions.removeSession('b')
    expect(snapshot(chatSessionsState).sessions.map((item) => item.id)).toEqual(['a', 'c'])
  })

  it('selects the personal tenant and loads v1 session summaries', async () => {
    server.use(
      tenantHandler,
      http.get(`${API_BASE}/api/v1/tenants/personal/sessions`, () =>
        HttpResponse.json([{ id: 'a', tenant_id: 'personal', created_by_user_id: 'u', title: null,
          created_at: now, updated_at: now, archived_at: null }]),
      ),
    )
    await chatSessionsActions.loadSessions()
    const state = snapshot(chatSessionsState)
    expect(state.tenant_id).toBe('personal')
    expect(state.status).toBe('loaded')
    expect(state.sessions[0].title).toBe('新对话')
  })

  it('loads durable message history from v1 detail', async () => {
    server.use(
      tenantHandler,
      http.get(`${API_BASE}/api/v1/tenants/personal/sessions/a`, ({ request }) => {
        expect(new URL(request.url).searchParams.get('limit')).toBe('1000')
        return HttpResponse.json({ id: 'a', tenant_id: 'personal', created_by_user_id: 'u', title: 'a',
          created_at: now, updated_at: now, archived_at: null, has_more: false,
          active_run_id: null, active_run_status: null,
          active_pause_type: null, active_pause_request: null,
          messages: [{ id: 'm1', role: 'assistant', content: 'durable', status: 'done', created_at: now }] })
      }),
    )
    const detail = await chatSessionsActions.loadSessionDetail('a')
    expect(detail.messages[0].content).toBe('durable')
  })

  it('renames and archives through tenant-scoped v1 endpoints', async () => {
    chatSessionsActions.setSessions([session('a')])
    server.use(
      tenantHandler,
      http.patch(`${API_BASE}/api/v1/tenants/personal/sessions/a`, async ({ request }) => {
        expect(await request.json()).toEqual({ title: 'new' })
        return HttpResponse.json({ id: 'a' })
      }),
      http.delete(`${API_BASE}/api/v1/tenants/personal/sessions/a`, () => new HttpResponse(null, { status: 204 })),
    )
    await chatSessionsActions.renameSession('a', 'new')
    expect(snapshot(chatSessionsState).sessions[0].title).toBe('new')
    await chatSessionsActions.deleteSession('a')
    expect(snapshot(chatSessionsState).sessions).toEqual([])
  })

  it('rolls optimistic mutations back when v1 requests fail', async () => {
    chatSessionsActions.setSessions([session('a')])
    server.use(
      tenantHandler,
      http.patch(`${API_BASE}/api/v1/tenants/personal/sessions/a`, () => new HttpResponse(null, { status: 500 })),
    )
    await expect(chatSessionsActions.renameSession('a', 'new')).rejects.toThrow()
    expect(snapshot(chatSessionsState).sessions[0].title).toBe('chat a')
  })
})
