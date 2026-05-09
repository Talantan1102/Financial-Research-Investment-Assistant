/**
 * frontend/src/store/chat-sessions.ts
 *
 * Multi-chat list state. Sorted by last_active_at desc.
 */

import { proxy } from 'valtio'
import type { ChatSession } from '@/types/chat'

export type ChatSessionsStatus = 'idle' | 'loading' | 'loaded' | 'error'

export interface ChatSessionsState {
  sessions: ChatSession[]
  status: ChatSessionsStatus
  error: string | null
}

const INITIAL: ChatSessionsState = {
  sessions: [],
  status: 'idle',
  error: null,
}

export const chatSessionsState = proxy<ChatSessionsState>({ ...INITIAL })

function sortDesc(a: ChatSession, b: ChatSession): number {
  if (a.last_active_at < b.last_active_at) return 1
  if (a.last_active_at > b.last_active_at) return -1
  return 0
}

export const chatSessionsActions = {
  setStatus(status: ChatSessionsStatus, error: string | null = null) {
    chatSessionsState.status = status
    chatSessionsState.error = error
  },
  setSessions(sessions: ChatSession[]) {
    chatSessionsState.sessions = [...sessions].sort(sortDesc)
    chatSessionsState.status = 'loaded'
    chatSessionsState.error = null
  },
  upsertSession(session: ChatSession) {
    const idx = chatSessionsState.sessions.findIndex((s) => s.id === session.id)
    if (idx >= 0) {
      chatSessionsState.sessions[idx] = session
    } else {
      chatSessionsState.sessions.push(session)
    }
    chatSessionsState.sessions.sort(sortDesc)
  },
  removeSession(id: string) {
    chatSessionsState.sessions = chatSessionsState.sessions.filter(
      (s) => s.id !== id,
    )
  },
  reset() {
    chatSessionsState.sessions = []
    chatSessionsState.status = 'idle'
    chatSessionsState.error = null
  },
}
