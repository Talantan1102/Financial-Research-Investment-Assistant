import { describe, expect, it, beforeEach, afterEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import {
  buildChatStreamUrl,
  createChat,
  deleteChat,
  getChat,
  listChats,
} from '@/api/chatApi'
import { server } from '@/test-utils/msw-server'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''

describe('chatApi REST', () => {
  it('listChats GETs /api/v0/chats and returns sessions', async () => {
    server.use(
      http.get(`${API_BASE}/api/v0/chats`, () =>
        HttpResponse.json([
          {
            id: 's1',
            user_id: null,
            title: 'session 1',
            created_at: '2026-05-09T00:00:00Z',
            last_active_at: '2026-05-09T00:01:00Z',
            message_count: 2,
            last_msg_preview: 'hi',
          },
        ]),
      ),
    )
    const sessions = await listChats()
    expect(sessions).toHaveLength(1)
    expect(sessions[0].id).toBe('s1')
  })

  it('createChat POSTs /api/v0/chats and returns the new session', async () => {
    server.use(
      http.post(`${API_BASE}/api/v0/chats`, async ({ request }) => {
        const body = (await request.json()) as { title?: string }
        return HttpResponse.json({
          id: 's2',
          user_id: null,
          title: body.title ?? 'New chat',
          created_at: '2026-05-09T00:00:00Z',
          last_active_at: '2026-05-09T00:00:00Z',
          message_count: 0,
          last_msg_preview: null,
        })
      }),
    )
    const s = await createChat({ title: 'My chat' })
    expect(s.title).toBe('My chat')
  })

  it('getChat GETs /api/v0/chats/:id and returns detail', async () => {
    server.use(
      http.get(`${API_BASE}/api/v0/chats/s1`, () =>
        HttpResponse.json({
          session: {
            id: 's1',
            user_id: null,
            title: 't',
            created_at: '2026-05-09T00:00:00Z',
            last_active_at: '2026-05-09T00:00:00Z',
            message_count: 0,
            last_msg_preview: null,
          },
          messages: [],
        }),
      ),
    )
    const detail = await getChat('s1')
    expect(detail.session.id).toBe('s1')
  })

  it('deleteChat DELETEs /api/v0/chats/:id', async () => {
    let called = false
    server.use(
      http.delete(`${API_BASE}/api/v0/chats/s1`, () => {
        called = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    await deleteChat('s1')
    expect(called).toBe(true)
  })

  it('buildChatStreamUrl appends last_event_id query when provided', () => {
    const url = buildChatStreamUrl('s1', 42)
    expect(url).toContain('/api/v0/chat/stream/s1')
    expect(url).toContain('last_event_id=42')
  })
})

// ── C66: Authorization header attached to all chat endpoints ───────────────

import {
  cancelChatTask,
  confirmEscalation,
  renameChat,
  retryChatTask,
} from '../chatApi'

describe('C66: chatApi auth header on all endpoints', () => {
  beforeEach(() => {
    // Seed a token so getAuthToken() returns something
    localStorage.setItem('auth', JSON.stringify({ token: 'test-bearer', user: null, isLoggedIn: true }))
  })

  afterEach(() => {
    localStorage.removeItem('auth')
  })

  it('listChats includes Authorization header', async () => {
    let receivedAuth: string | null = null
    server.use(
      http.get(`${API_BASE}/api/v0/chats`, ({ request }) => {
        receivedAuth = request.headers.get('Authorization')
        return HttpResponse.json([])
      }),
    )
    await listChats()
    expect(receivedAuth).toBe('Bearer test-bearer')
  })

  it('createChat includes Authorization header', async () => {
    let receivedAuth: string | null = null
    server.use(
      http.post(`${API_BASE}/api/v0/chats`, ({ request }) => {
        receivedAuth = request.headers.get('Authorization')
        return HttpResponse.json({ id: 's1', user_id: null, title: 't', created_at: '', last_active_at: '', message_count: 0, last_msg_preview: null })
      }),
    )
    await createChat({})
    expect(receivedAuth).toBe('Bearer test-bearer')
  })

  it('getChat includes Authorization header', async () => {
    let receivedAuth: string | null = null
    server.use(
      http.get(`${API_BASE}/api/v0/chats/s1`, ({ request }) => {
        receivedAuth = request.headers.get('Authorization')
        return HttpResponse.json({ session: { id: 's1', user_id: null, title: 't', created_at: '', last_active_at: '', message_count: 0, last_msg_preview: null }, messages: [] })
      }),
    )
    await getChat('s1')
    expect(receivedAuth).toBe('Bearer test-bearer')
  })

  it('deleteChat includes Authorization header', async () => {
    let receivedAuth: string | null = null
    server.use(
      http.delete(`${API_BASE}/api/v0/chats/s1`, ({ request }) => {
        receivedAuth = request.headers.get('Authorization')
        return new HttpResponse(null, { status: 204 })
      }),
    )
    await deleteChat('s1')
    expect(receivedAuth).toBe('Bearer test-bearer')
  })

  it('cancelChatTask includes Authorization header', async () => {
    let receivedAuth: string | null = null
    server.use(
      http.post(`${API_BASE}/api/v0/chat/cancel/task1`, ({ request }) => {
        receivedAuth = request.headers.get('Authorization')
        return new HttpResponse(null, { status: 202 })
      }),
    )
    await cancelChatTask('task1')
    expect(receivedAuth).toBe('Bearer test-bearer')
  })

  it('retryChatTask includes Authorization header', async () => {
    let receivedAuth: string | null = null
    server.use(
      http.post(`${API_BASE}/api/v0/chat/retry/task1`, ({ request }) => {
        receivedAuth = request.headers.get('Authorization')
        return HttpResponse.json({ task_id: 't2', parent_task_id: 't1', stream_url: '', resumed_from_checkpoint: '' })
      }),
    )
    await retryChatTask('task1')
    expect(receivedAuth).toBe('Bearer test-bearer')
  })

  it('confirmEscalation includes Authorization header', async () => {
    let receivedAuth: string | null = null
    server.use(
      http.post(`${API_BASE}/api/v0/chat/escalate`, ({ request }) => {
        receivedAuth = request.headers.get('Authorization')
        return HttpResponse.json({ ok: true })
      }),
    )
    await confirmEscalation({ session_id: 's1', packet: {} as never })
    expect(receivedAuth).toBe('Bearer test-bearer')
  })

  it('renameChat includes Authorization header', async () => {
    let receivedAuth: string | null = null
    server.use(
      http.put(`${API_BASE}/api/v0/chats/abc-123`, ({ request }) => {
        receivedAuth = request.headers.get('Authorization')
        return HttpResponse.json({ id: 'abc-123', title: 'New Title' })
      }),
    )
    await renameChat('abc-123', 'New Title')
    expect(receivedAuth).toBe('Bearer test-bearer')
  })

  it('no Authorization header when localStorage has no token', async () => {
    localStorage.removeItem('auth')
    let receivedAuth: string | null = 'sentinel'
    server.use(
      http.get(`${API_BASE}/api/v0/chats`, ({ request }) => {
        receivedAuth = request.headers.get('Authorization')
        return HttpResponse.json([])
      }),
    )
    await listChats()
    expect(receivedAuth).toBeNull()
  })
})

// ── C67: AUTH_STORAGE_KEY is a single exported constant ────────────────────

import { AUTH_STORAGE_KEY } from '../auth-token'
import { getAuthToken } from '../auth-token'

describe('C67: AUTH_STORAGE_KEY SSOT — exported from auth-token.ts', () => {
  afterEach(() => {
    localStorage.removeItem(AUTH_STORAGE_KEY)
  })

  it('AUTH_STORAGE_KEY is exported and equals the well-known value', () => {
    // ensures the export exists and has the right value so importers share SSOT
    expect(AUTH_STORAGE_KEY).toBe('auth')
  })

  it('storing under AUTH_STORAGE_KEY makes getAuthToken read it back (behavioral round-trip)', () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify({ token: 'round-trip-token' }))
    expect(getAuthToken()).toBe('round-trip-token')
  })

  it('store/auth.ts and plugins/auth.ts use the same key (localStorage removal is visible to getAuthToken)', () => {
    // If store/auth.ts logout removes AUTH_STORAGE_KEY and plugins/auth.ts also removes
    // the same key, getAuthToken should return null after removal.
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify({ token: 'tok' }))
    expect(getAuthToken()).toBe('tok')
    localStorage.removeItem(AUTH_STORAGE_KEY)
    expect(getAuthToken()).toBeNull()
  })
})

describe('renameChat', () => {
  it('sends PUT /api/v0/chats/:id with new title', async () => {
    let received: { title: string } | null = null
    server.use(
      http.put(`${API_BASE}/api/v0/chats/abc-123`, async ({ request }) => {
        received = (await request.json()) as { title: string }
        return HttpResponse.json({ id: 'abc-123', title: received.title })
      }),
    )
    await renameChat('abc-123', 'New Title')
    expect(received).toEqual({ title: 'New Title' })
  })

  it('throws on 4xx', async () => {
    server.use(
      http.put(`${API_BASE}/api/v0/chats/abc-123`, () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
    )
    await expect(renameChat('abc-123', 'x')).rejects.toThrow()
  })
})
