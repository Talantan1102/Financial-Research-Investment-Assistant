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

export interface CostBreakdown {
  chat_usd: number
  research_usd: number
  total_usd: number
}

export type StreamingPhase =
  | 'idle'
  | 'thinking'
  | 'tool'
  | 'writing'
  | 'research_planning'
  | 'research_running'
  | 'research_writing'
  | 'error'

export interface CurrentChatState {
  session_id: string | null
  // Plan 3 Task 7: 当前 in-flight task(streaming 中)的 UUID。
  // sendMessage 拿到 POST /chat 返的 task_id 后 set;done/error event 后 clear。
  // InputArea 据此切换 send ↔ stop button;ChatPane 据此判断是否要 cancel。
  active_task_id: string | null
  messages: ChatMessage[]
  streamingStatus: StreamingStatus
  streamingDraft: string
  last_seq: number
  cost_so_far: number
  cost_breakdown: CostBreakdown
  toolEvents: SSEEvent[]
  errorMessage: string | null
  streaming_phase: StreamingPhase
  streaming_phase_label?: string
}

const INITIAL: CurrentChatState = {
  session_id: null,
  active_task_id: null,
  messages: [],
  streamingStatus: 'idle',
  streamingDraft: '',
  last_seq: 0,
  cost_so_far: 0,
  cost_breakdown: { chat_usd: 0, research_usd: 0, total_usd: 0 },
  toolEvents: [],
  errorMessage: null,
  streaming_phase: 'idle',
  streaming_phase_label: undefined,
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
    currentChatState.active_task_id = null
    currentChatState.messages = [...messages]
    currentChatState.streamingStatus = 'idle'
    currentChatState.streamingDraft = ''
    currentChatState.last_seq = 0
    currentChatState.cost_so_far = 0
    currentChatState.cost_breakdown = { chat_usd: 0, research_usd: 0, total_usd: 0 }
    currentChatState.toolEvents = []
    currentChatState.errorMessage = null
  },
  setActiveTaskId(taskId: string | null) {
    currentChatState.active_task_id = taskId
  },
  beginStreaming() {
    currentChatState.streamingStatus = 'streaming'
    currentChatState.streamingDraft = ''
    currentChatState.errorMessage = null
  },
  resumeStreaming() {
    // Like beginStreaming but preserves streamingDraft for F6 reconnect continuity
    currentChatState.streamingStatus = 'streaming'
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
        // Plan 3 Task 7: terminal event → clear in-flight task tracker
        currentChatState.active_task_id = null
        currentChatState.toolEvents.push(ev as DoneEvent)
        break
      case 'error':
        currentChatState.streamingStatus = 'error'
        currentChatState.errorMessage = (ev as ErrorEvent).error
        // Plan 3 Task 7: terminal event → clear in-flight task tracker
        currentChatState.active_task_id = null
        currentChatState.toolEvents.push(ev as ErrorEvent)
        break
      default:
        currentChatState.toolEvents.push(ev)
    }
  },
  setStreamingPhase(phase: StreamingPhase, label?: string) {
    currentChatState.streaming_phase = phase
    currentChatState.streaming_phase_label = label
  },
  reset() {
    currentChatState.session_id = INITIAL.session_id
    currentChatState.active_task_id = INITIAL.active_task_id
    currentChatState.messages = []
    currentChatState.streamingStatus = INITIAL.streamingStatus
    currentChatState.streamingDraft = INITIAL.streamingDraft
    currentChatState.last_seq = INITIAL.last_seq
    currentChatState.cost_so_far = INITIAL.cost_so_far
    currentChatState.cost_breakdown = { ...INITIAL.cost_breakdown }
    currentChatState.toolEvents = []
    currentChatState.errorMessage = null
    currentChatState.streaming_phase = INITIAL.streaming_phase
    currentChatState.streaming_phase_label = INITIAL.streaming_phase_label
  },
}
