/**
 * frontend/src/store/chat-sessions.ts
 *
 * Multi-chat list state. Sorted by updated_at desc.
 */

import { proxy } from 'valtio'
import { createChat, deleteChat, listChats, renameChat } from '@/api/chatApi'
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
  // backend chats router 返 `updated_at` — 排序时直接使用。
  // unshift(新建 session 顶置)在 upsertSession 中处理,避免 naive UTC 字符串
  // 排序偏差问题。
  return s.updated_at
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
  async deleteSession(id: string): Promise<void> {
    // Optimistic: remove from list immediately, rollback on failure (fail-loud).
    const prev = [...chatSessionsState.sessions]
    const idx = chatSessionsState.sessions.findIndex((s) => s.id === id)
    if (idx < 0) return
    chatSessionsState.sessions = chatSessionsState.sessions.filter(
      (s) => s.id !== id,
    )
    try {
      await deleteChat(id)
    } catch (e) {
      chatSessionsState.sessions = prev
      throw e
    }
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
  /**
   * Shared by the /chat landing page and the sidebar "新对话" button to avoid
   * accumulating empty sessions. Reuses the first untouched empty shell
   * (message_count === 0, default title) if one exists; otherwise creates a new
   * one. This means clicking "新对话" while already sitting on an empty chat
   * stays on that chat instead of spawning a duplicate.
   *
   * SSOT: "新对话" matches backend chats.py DEFAULT_CHAT_TITLE constant.
   */
  async getOrCreateEmptyChat(): Promise<ChatSession> {
    if (chatSessionsState.status !== 'loaded') {
      try {
        await chatSessionsActions.loadSessions()
      } catch {
        // loadSessions failed — fall through to create a fresh session
        return chatSessionsActions.createAndAdd()
      }
    }
    const empty = chatSessionsState.sessions.find(
      (s) => s.message_count === 0 && s.title === '新对话',
    )
    if (empty) return empty
    return chatSessionsActions.createAndAdd()
  },
}
