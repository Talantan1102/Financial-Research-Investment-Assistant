import { describe, expect, it, beforeEach } from 'vitest'
import { snapshot } from 'valtio'
import {
  chatSessionsActions,
  chatSessionsState,
} from '@/store/chat-sessions'
import type { ChatSession } from '@/types/chat'

const session = (id: string, lastActive: string): ChatSession => ({
  id,
  user_id: null,
  title: `chat ${id}`,
  created_at: '2026-05-09T00:00:00Z',
  last_active_at: lastActive,
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
    expect(s.sessions[0].last_active_at).toBe('2026-05-09T02:00:00Z')
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
