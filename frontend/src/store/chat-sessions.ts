import { proxy } from 'valtio'
import {
  archiveRunSession,
  getRunSession,
  listRunSessions,
  listTenants,
  renameRunSession,
  type RunSessionDetail,
  type RunSessionSummary,
} from '@/api/runApi'
import type { ChatSession } from '@/types/chat'

export type ChatSessionsStatus = 'idle' | 'loading' | 'loaded' | 'error'
export interface ChatSessionsState {
  tenant_id: string | null
  sessions: ChatSession[]
  status: ChatSessionsStatus
  error: string | null
}

const INITIAL: ChatSessionsState = { tenant_id: null, sessions: [], status: 'idle', error: null }
export const chatSessionsState = proxy<ChatSessionsState>({ ...INITIAL })

function asChatSession(session: RunSessionSummary): ChatSession {
  return {
    id: session.id,
    title: session.title ?? '新对话',
    created_at: session.created_at,
    updated_at: session.updated_at,
    message_count: 0,
    last_msg_preview: null,
  }
}

async function ensureTenantId(): Promise<string> {
  if (chatSessionsState.tenant_id) return chatSessionsState.tenant_id
  const tenants = await listTenants()
  const tenant = tenants.find((candidate) => candidate.is_personal) ?? tenants[0]
  if (!tenant) throw new Error('No accessible tenant')
  chatSessionsState.tenant_id = tenant.id
  return tenant.id
}

export const chatSessionsActions = {
  setStatus(status: ChatSessionsStatus, error: string | null = null) {
    chatSessionsState.status = status
    chatSessionsState.error = error
  },
  setSessions(sessions: ChatSession[]) {
    chatSessionsState.sessions = [...sessions].sort((a, b) =>
      a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : 0,
    )
    chatSessionsState.status = 'loaded'
    chatSessionsState.error = null
  },
  upsertSession(session: ChatSession) {
    const index = chatSessionsState.sessions.findIndex((item) => item.id === session.id)
    if (index >= 0) chatSessionsState.sessions[index] = session
    else chatSessionsState.sessions.unshift(session)
  },
  removeSession(id: string) {
    chatSessionsState.sessions = chatSessionsState.sessions.filter((session) => session.id !== id)
  },
  async resolveTenantId(): Promise<string> {
    return ensureTenantId()
  },
  async loadSessions(): Promise<void> {
    chatSessionsState.status = 'loading'
    chatSessionsState.error = null
    try {
      const sessions = await listRunSessions(await ensureTenantId())
      chatSessionsActions.setSessions(sessions.map(asChatSession))
    } catch (error) {
      chatSessionsState.status = 'error'
      chatSessionsState.error = (error as Error).message
      throw error
    }
  },
  async loadSessionDetail(sessionId: string): Promise<RunSessionDetail> {
    return getRunSession(await ensureTenantId(), sessionId)
  },
  async deleteSession(id: string): Promise<void> {
    const previous = [...chatSessionsState.sessions]
    if (!previous.some((session) => session.id === id)) return
    chatSessionsActions.removeSession(id)
    try {
      await archiveRunSession(await ensureTenantId(), id)
    } catch (error) {
      chatSessionsState.sessions = previous
      throw error
    }
  },
  async renameSession(id: string, newTitle: string): Promise<void> {
    const index = chatSessionsState.sessions.findIndex((session) => session.id === id)
    if (index < 0) return
    const previousTitle = chatSessionsState.sessions[index].title
    chatSessionsState.sessions[index].title = newTitle
    try {
      await renameRunSession(await ensureTenantId(), id, newTitle)
    } catch (error) {
      chatSessionsState.sessions[index].title = previousTitle
      throw error
    }
  },
  reset() {
    chatSessionsState.tenant_id = null
    chatSessionsState.sessions = []
    chatSessionsState.status = 'idle'
    chatSessionsState.error = null
  },
}
