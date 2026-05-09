/**
 * frontend/src/store/current-chat.ts
 *
 * Currently active chat session — messages list, streaming draft, cost meter,
 * last_seq for SSE reconnect.
 *
 * dispatchEvent is the single source of truth for SSE event → state mutation.
 * Event ordering enforced by last_seq comparison (G1).
 */

import { proxy } from 'valtio'
import type {
  ChatMessage,
  CostUpdateEvent,
  DoneEvent,
  ErrorEvent,
  SSEEvent,
  TokenEvent,
} from '@/types/chat'

export type StreamingStatus = 'idle' | 'streaming' | 'reconnecting' | 'error'

export interface CurrentChatState {
  session_id: string | null
  messages: ChatMessage[]
  streamingStatus: StreamingStatus
  streamingDraft: string
  last_seq: number
  cost_so_far: number
  toolEvents: SSEEvent[]
  errorMessage: string | null
}

const INITIAL: CurrentChatState = {
  session_id: null,
  messages: [],
  streamingStatus: 'idle',
  streamingDraft: '',
  last_seq: 0,
  cost_so_far: 0,
  toolEvents: [],
  errorMessage: null,
}

export const currentChatState = proxy<CurrentChatState>({ ...INITIAL })

function flushDraftAsMessage() {
  if (!currentChatState.streamingDraft) return
  if (!currentChatState.session_id) return
  currentChatState.messages.push({
    id: `local-${Date.now()}`,
    session_id: currentChatState.session_id,
    role: 'assistant',
    content: currentChatState.streamingDraft,
    message_type: 'text',
    tool_call_data: null,
    research_report_id: null,
    research_report_summary: null,
    created_at: new Date().toISOString(),
  })
  currentChatState.streamingDraft = ''
}

export const currentChatActions = {
  setSession(session_id: string, messages: ChatMessage[]) {
    currentChatState.session_id = session_id
    currentChatState.messages = [...messages]
    currentChatState.streamingStatus = 'idle'
    currentChatState.streamingDraft = ''
    currentChatState.last_seq = 0
    currentChatState.cost_so_far = 0
    currentChatState.toolEvents = []
    currentChatState.errorMessage = null
  },
  beginStreaming() {
    currentChatState.streamingStatus = 'streaming'
    currentChatState.streamingDraft = ''
    currentChatState.errorMessage = null
  },
  setReconnecting() {
    currentChatState.streamingStatus = 'reconnecting'
  },
  appendUserMessage(content: string) {
    if (!currentChatState.session_id) return
    currentChatState.messages.push({
      id: `local-user-${Date.now()}`,
      session_id: currentChatState.session_id,
      role: 'user',
      content,
      message_type: 'text',
      tool_call_data: null,
      research_report_id: null,
      research_report_summary: null,
      created_at: new Date().toISOString(),
    })
  },
  dispatchEvent(ev: SSEEvent) {
    if (ev.seq <= currentChatState.last_seq) return
    currentChatState.last_seq = ev.seq

    switch (ev.type) {
      case 'token':
        currentChatState.streamingDraft += (ev as TokenEvent).content
        break
      case 'cost_update':
        currentChatState.cost_so_far = (ev as CostUpdateEvent).cost_so_far
        currentChatState.toolEvents.push(ev)
        break
      case 'done':
        flushDraftAsMessage()
        currentChatState.streamingStatus = 'idle'
        currentChatState.toolEvents.push(ev as DoneEvent)
        break
      case 'error':
        currentChatState.streamingStatus = 'error'
        currentChatState.errorMessage = (ev as ErrorEvent).error
        currentChatState.toolEvents.push(ev as ErrorEvent)
        break
      default:
        currentChatState.toolEvents.push(ev)
    }
  },
  reset() {
    currentChatState.session_id = INITIAL.session_id
    currentChatState.messages = []
    currentChatState.streamingStatus = INITIAL.streamingStatus
    currentChatState.streamingDraft = INITIAL.streamingDraft
    currentChatState.last_seq = INITIAL.last_seq
    currentChatState.cost_so_far = INITIAL.cost_so_far
    currentChatState.toolEvents = []
    currentChatState.errorMessage = null
  },
}
