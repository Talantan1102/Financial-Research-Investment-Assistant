import { describe, expect, it, beforeEach } from 'vitest'
import { snapshot } from 'valtio'
import {
  chatSessionsActions,
  chatSessionsState,
} from '@/store/chat-sessions'
import type { ChatSession } from '@/types/chat'
import { http, HttpResponse } from 'msw'
import { server } from '@/test-utils/msw-server'

const session = (id: string, lastActive: string): ChatSession => ({
  id,
  user_id: null,
  title: `chat ${id}`,
  created_at: '2026-05-09T00:00:00Z',
  updated_at: lastActive,
  message_count: 0,
  last_msg_preview: null,
})

describe('chatSessionsStore', () => {
  beforeEach(() => {
    chatSessionsActions.reset()
  })

  it('starts with empty list and idle status', () => {
    const s = snapshot(chatSessionsState)
    expect(s.sessions).toEqual([])
    expect(s.status).toBe('idle')
  })

  it('setSessions sorts by last_active_at desc', () => {
    chatSessionsActions.setSessions([
      session('a', '2026-05-09T00:00:00Z'),
      session('b', '2026-05-09T01:00:00Z'),
      session('c', '2026-05-08T00:00:00Z'),
    ])
    const s = snapshot(chatSessionsState)
    expect(s.sessions.map((x) => x.id)).toEqual(['b', 'a', 'c'])
  })

  it('upsertSession adds when new, replaces when existing', () => {
    chatSessionsActions.upsertSession(session('a', '2026-05-09T00:00:00Z'))
    chatSessionsActions.upsertSession(session('a', '2026-05-09T02:00:00Z'))
    const s = snapshot(chatSessionsState)
    expect(s.sessions).toHaveLength(1)
    expect(s.sessions[0].updated_at).toBe('2026-05-09T02:00:00Z')
  })

  it('removeSession drops by id', () => {
    chatSessionsActions.setSessions([
      session('a', '2026-05-09T00:00:00Z'),
      session('b', '2026-05-09T00:00:00Z'),
    ])
    chatSessionsActions.removeSession('a')
    const s = snapshot(chatSessionsState)
    expect(s.sessions.map((x) => x.id)).toEqual(['b'])
  })
})

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''

describe('renameSession action', () => {
  beforeEach(() => {
    chatSessionsActions.reset()
    chatSessionsState.sessions = [
      {
        id: 'a',
        user_id: null,
        title: 'old',
        created_at: '2026-05-17T00:00:00Z',
        updated_at: '2026-05-17T00:00:00Z',
        message_count: 0,
        last_msg_preview: null,
      },
    ]
  })

  it('optimistically updates title then calls API', async () => {
    server.use(
      http.put(`${API_BASE}/api/v0/chats/a`, () => new HttpResponse(null, { status: 200 })),
    )
    const p = chatSessionsActions.renameSession('a', 'new')
    // optimistic: title updated synchronously before await
    expect(chatSessionsState.sessions[0].title).toBe('new')
    await p
    const s = snapshot(chatSessionsState)
    expect(s.sessions[0].title).toBe('new')
  })

  it('rolls back on API failure', async () => {
    server.use(
      http.put(`${API_BASE}/api/v0/chats/a`, () => new HttpResponse(null, { status: 500 })),
    )
    await expect(chatSessionsActions.renameSession('a', 'new')).rejects.toThrow()
    const s = snapshot(chatSessionsState)
    expect(s.sessions[0].title).toBe('old')
  })

  it('no-ops when session id not found', async () => {
    await expect(
      chatSessionsActions.renameSession('nonexistent', 'new'),
    ).resolves.toBeUndefined()
    const s = snapshot(chatSessionsState)
    expect(s.sessions[0].title).toBe('old')
  })
})

describe('chatSessionsStore + chatApi', () => {
  beforeEach(() => chatSessionsActions.reset())

  it('loadSessions sets status loading→loaded and populates list', async () => {
    server.use(
      http.get(`${API_BASE}/api/v0/chats`, () =>
        HttpResponse.json([
          {
            id: 'a',
            user_id: null,
            title: 'a',
            created_at: '2026-05-09T00:00:00Z',
            last_active_at: '2026-05-09T00:00:00Z',
            message_count: 0,
            last_msg_preview: null,
          },
        ]),
      ),
    )
    await chatSessionsActions.loadSessions()
    const s = snapshot(chatSessionsState)
    expect(s.status).toBe('loaded')
    expect(s.sessions).toHaveLength(1)
  })

  it('createAndAdd POSTs new chat then upserts', async () => {
    server.use(
      http.post(`${API_BASE}/api/v0/chats`, () =>
        HttpResponse.json({
          id: 'new-id',
          user_id: null,
          title: 'New chat',
          created_at: '2026-05-09T00:00:00Z',
          last_active_at: '2026-05-09T00:00:00Z',
          message_count: 0,
          last_msg_preview: null,
        }),
      ),
    )
    const created = await chatSessionsActions.createAndAdd()
    expect(created.id).toBe('new-id')
    const s = snapshot(chatSessionsState)
    expect(s.sessions.map((x) => x.id)).toContain('new-id')
  })
})
