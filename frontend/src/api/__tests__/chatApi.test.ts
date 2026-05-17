import { describe, expect, it } from 'vitest'
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

import { renameChat } from '../chatApi'

describe('renameChat', () => {
  it('sends PUT /api/sessions/:id with new title', async () => {
    let received: { title: string } | null = null
    server.use(
      http.put('/api/sessions/abc-123', async ({ request }) => {
        received = (await request.json()) as { title: string }
        return HttpResponse.json({ id: 'abc-123', title: received.title })
      }),
    )
    await renameChat('abc-123', 'New Title')
    expect(received).toEqual({ title: 'New Title' })
  })

  it('throws on 4xx', async () => {
    server.use(
      http.put('/api/sessions/abc-123', () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
    )
    await expect(renameChat('abc-123', 'x')).rejects.toThrow()
  })
})
