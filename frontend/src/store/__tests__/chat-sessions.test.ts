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

describe('getOrCreateEmptyChat action', () => {
  beforeEach(() => chatSessionsActions.reset())

  // Registers a POST /api/v0/chats handler that records how many times it is
  // hit and returns a freshly-created session. Lets each test assert whether
  // createChat (the only POST to this endpoint) fired — the "reuse empty shell"
  // path must hit it 0 times. server.resetHandlers() in vitest.setup.ts clears
  // this between tests so the counter never leaks.
  const stubCreateChat = (): { count: number } => {
    const calls = { count: 0 }
    server.use(
      http.post(`${API_BASE}/api/v0/chats`, () => {
        calls.count += 1
        return HttpResponse.json({
          id: 'created-id',
          user_id: null,
          title: '新对话',
          created_at: '2026-05-20T00:00:00Z',
          updated_at: '2026-05-20T00:00:00Z',
          message_count: 0,
          last_msg_preview: null,
        })
      }),
    )
    return calls
  }

  const emptyShell = (id: string): ChatSession => ({
    id,
    user_id: null,
    title: '新对话', // SSOT: matches backend chats.py DEFAULT_CHAT_TITLE
    created_at: '2026-05-20T00:00:00Z',
    updated_at: '2026-05-20T00:00:00Z',
    message_count: 0,
    last_msg_preview: null,
  })

  it('reuses an existing empty shell and does NOT call createChat', async () => {
    // setSessions flips status to 'loaded', so getOrCreateEmptyChat skips the
    // loadSessions branch and inspects the list directly.
    chatSessionsActions.setSessions([emptyShell('empty-1')])
    const calls = stubCreateChat()

    const result = await chatSessionsActions.getOrCreateEmptyChat()

    expect(result.id).toBe('empty-1')
    expect(calls.count).toBe(0) // reused, no duplicate creation
    const s = snapshot(chatSessionsState)
    expect(s.sessions.map((x) => x.id)).toEqual(['empty-1'])
  })

  it('does NOT reuse a session with messages — creates a new one', async () => {
    chatSessionsActions.setSessions([
      { ...emptyShell('busy-1'), title: '新对话', message_count: 3 },
    ])
    const calls = stubCreateChat()

    const result = await chatSessionsActions.getOrCreateEmptyChat()

    expect(result.id).toBe('created-id')
    expect(calls.count).toBe(1)
    const s = snapshot(chatSessionsState)
    expect(s.sessions.map((x) => x.id)).toContain('created-id')
  })

  it('does NOT reuse a renamed empty session — title must match default', async () => {
    chatSessionsActions.setSessions([
      { ...emptyShell('renamed-1'), title: '我的研究', message_count: 0 },
    ])
    const calls = stubCreateChat()

    const result = await chatSessionsActions.getOrCreateEmptyChat()

    expect(result.id).toBe('created-id')
    expect(calls.count).toBe(1)
  })

  it('creates a new chat when the list is empty but already loaded', async () => {
    chatSessionsActions.setSessions([]) // loaded, empty list
    const calls = stubCreateChat()

    const result = await chatSessionsActions.getOrCreateEmptyChat()

    expect(result.id).toBe('created-id')
    expect(calls.count).toBe(1)
  })

  it('loads sessions first when status is not loaded, then reuses empty shell', async () => {
    // status starts 'idle' (after reset) → must GET /api/v0/chats before judging.
    let listed = 0
    server.use(
      http.get(`${API_BASE}/api/v0/chats`, () => {
        listed += 1
        return HttpResponse.json([
          {
            id: 'fetched-empty',
            user_id: null,
            title: '新对话',
            created_at: '2026-05-20T00:00:00Z',
            updated_at: '2026-05-20T00:00:00Z',
            message_count: 0,
            last_msg_preview: null,
          },
        ])
      }),
    )
    const calls = stubCreateChat()

    expect(snapshot(chatSessionsState).status).toBe('idle')
    const result = await chatSessionsActions.getOrCreateEmptyChat()

    expect(listed).toBe(1) // loadSessions ran because status !== 'loaded'
    expect(result.id).toBe('fetched-empty')
    expect(calls.count).toBe(0) // reused the fetched shell, no creation
  })
})
