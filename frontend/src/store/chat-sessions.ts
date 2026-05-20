/**
 * frontend/src/store/chat-sessions.ts
 *
 * Multi-chat list state. Sorted by last_active_at desc.
 */

import { proxy } from 'valtio'
import { createChat, listChats, renameChat } from '@/api/chatApi'
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

function activityTs(s: ChatSession): string {
  // backend chats router 返 `updated_at` 不返 `last_active_at`;为新建 session
  // 排到列表顶部,优先取 last_active_at 兜底 updated_at。
  return s.last_active_at || (s as { updated_at?: string }).updated_at || ''
}

function sortDesc(a: ChatSession, b: ChatSession): number {
  const ta = activityTs(a)
  const tb = activityTs(b)
  if (ta < tb) return 1
  if (ta > tb) return -1
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
      // 新建 session: unshift 到顶部,不依赖 sort。backend chats router 返
      // updated_at 时区标记不一致(naive UTC 数值带 +08:00 后缀),按字符串
      // 排序会把 "15:18+08:00" 错排到 "22:14+08:00" 后面,新 session 显示
      // 在中部而非顶部。unshift 直接保证 ChatGPT 风顺序(刚创建立刻可见)。
      chatSessionsState.sessions.unshift(session)
    }
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
  async loadSessions() {
    chatSessionsState.status = 'loading'
    chatSessionsState.error = null
    try {
      const list = await listChats()
      chatSessionsActions.setSessions(list)
    } catch (e) {
      chatSessionsState.status = 'error'
      chatSessionsState.error = (e as Error).message
      throw e
    }
  },
  async createAndAdd(title?: string) {
    const created = await createChat(title === undefined ? {} : { title })
    chatSessionsActions.upsertSession(created)
    return created
  },
  async renameSession(id: string, newTitle: string): Promise<void> {
    const idx = chatSessionsState.sessions.findIndex((s) => s.id === id)
    if (idx < 0) return
    const prevTitle = chatSessionsState.sessions[idx].title
    chatSessionsState.sessions[idx].title = newTitle // optimistic update
    try {
      await renameChat(id, newTitle)
    } catch (e) {
      chatSessionsState.sessions[idx].title = prevTitle // rollback
      throw e
    }
  },
}
