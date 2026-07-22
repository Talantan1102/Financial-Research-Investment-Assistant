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
import { paperTradingActions } from '@/store/paper-trading'
import type {
  ChatMessage,
  ChartEvent,
  CostUpdateEvent,
  DispatchEndEvent,
  DispatchStartEvent,
  DoneEvent,
  ErrorEvent,
  LoopHaltEvent,
  SSEEvent,
  StepStartEvent,
  ToolEndEvent,
  TokenEvent,
} from '@/types/chat'

export type StreamingStatus = 'idle' | 'streaming' | 'reconnecting' | 'error'

export interface CostBreakdown {
  chat_usd: number
  research_usd: number
  total_usd: number
}

// chatloop loop progress (spec § 5.1 step_start{step,max_steps}) — drives the
// "第 N/M 步" hint in StreamingIndicator.
export interface LoopProgress {
  step: number
  max_steps: number
}

// dispatch_subagents fan-out: one lane per child subtask. dispatch_start seeds
// the lanes (status=running, toolCount=0); each child tool_end{lane} increments
// the matching lane's toolCount; dispatch_end stamps each lane's terminal status.
export interface DispatchLane {
  subtask_id: string
  goal: string
  toolCount: number
  status: 'running' | 'ok' | 'partial' | 'failed'
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
  // chatloop loop progress + halt reason (spec § 5.1). loop_progress feeds the
  // "第 N/M 步" indicator; halt_reason (non-natural) surfaces the halt banner
  // ("已达执行上限(...)") and is kept after done so the banner persists.
  loop_progress: LoopProgress | null
  halt_reason: string | null
  // dispatch_subagents fan-out progress — N parallel child-loop lanes. Empty
  // when no dispatch is in flight; reset on every cleanup path.
  dispatchLanes: DispatchLane[]
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
  loop_progress: null,
  halt_reason: null,
  dispatchLanes: [],
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
    currentChatState.loop_progress = null
    currentChatState.halt_reason = null
    currentChatState.dispatchLanes = []
    // Approval cards are session-scoped. Rebuild them from the persisted
    // message history so a refresh/session switch does not lose pending cards
    // or leak cards from the previous chat.
    paperTradingActions.reset()
    for (const message of messages) {
      if (message.message_type !== 'paper_approval' || !message.tool_call_data) continue
      const data = message.tool_call_data
      if (
        typeof data === 'object' &&
        data !== null &&
        'approval_id' in data &&
        'approval_type' in data &&
        'resource_id' in data &&
        'proposal' in data &&
        'preview' in data &&
        'expires_at' in data
      ) {
        paperTradingActions.upsert(data as Parameters<typeof paperTradingActions.upsert>[0])
      }
    }
  },
  setActiveTaskId(taskId: string | null) {
    currentChatState.active_task_id = taskId
  },
  beginStreaming() {
    currentChatState.streamingStatus = 'streaming'
    currentChatState.streamingDraft = ''
    currentChatState.last_seq = 0 // C32: reset seq so 2nd+ messages don't dedup all events
    currentChatState.errorMessage = null
    // fresh turn — clear prior loop progress + halt banner
    currentChatState.loop_progress = null
    currentChatState.halt_reason = null
    // fresh turn — drop any prior fan-out lanes
    currentChatState.dispatchLanes = []
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
        // chatloop payload carries both `content` and `text`; prefer content.
        currentChatState.streamingDraft +=
          (ev as TokenEvent).content ?? (ev as TokenEvent).text ?? ''
        // first token of the step → writing phase
        currentChatState.streaming_phase = 'writing'
        break
      case 'reasoning':
        // Minimal (spec § 5.1): keep reasoning in toolEvents for later UI; no
        // separate reasoningDraft rendering yet.
        currentChatState.toolEvents.push(ev)
        break
      case 'step_start': {
        const e = ev as StepStartEvent
        currentChatState.loop_progress = { step: e.step, max_steps: e.max_steps }
        currentChatState.streaming_phase = 'thinking'
        currentChatState.toolEvents.push(ev)
        break
      }
      case 'tool_call':
        currentChatState.streaming_phase = 'tool'
        currentChatState.toolEvents.push(ev)
        break
      case 'tool_start':
        currentChatState.streaming_phase = 'tool'
        currentChatState.toolEvents.push(ev)
        break
      case 'tool_end': {
        // dispatch_subagents: child-loop tool_end carries lane=subtask_id →
        // bump the matching lane's取数 counter.
        const laneId = (ev as ToolEndEvent).lane
        if (laneId) {
          const lane = currentChatState.dispatchLanes.find((l) => l.subtask_id === laneId)
          if (lane) lane.toolCount += 1
        }
        currentChatState.toolEvents.push(ev)
        break
      }
      case 'tool_error':
        currentChatState.toolEvents.push(ev)
        break
      case 'dispatch_start':
        currentChatState.dispatchLanes = (ev as DispatchStartEvent).subtasks.map((s) => ({
          subtask_id: s.subtask_id,
          goal: s.goal,
          toolCount: 0,
          status: 'running',
        }))
        currentChatState.toolEvents.push(ev)
        break
      case 'dispatch_end':
        for (const r of (ev as DispatchEndEvent).results) {
          const lane = currentChatState.dispatchLanes.find(
            (l) => l.subtask_id === r.subtask_id,
          )
          if (lane) lane.status = r.status
        }
        currentChatState.toolEvents.push(ev)
        break
      case 'chart': {
        const e = ev as ChartEvent
        if (currentChatState.session_id) {
          currentChatState.messages.push({
            id: `local-chart-${e.chart_id}`,
            session_id: currentChatState.session_id,
            role: 'assistant',
            content: '',
            message_type: 'chart',
            tool_call_data: null,
            research_report_id: null,
            research_report_summary: null,
            created_at: new Date().toISOString(),
            chart_spec: { type: 'plotly', figure: e.figure },
          })
        }
        break
      }
      case 'steer_merged':
        // System bubble rendered from this event (preview of merged instruction).
        currentChatState.toolEvents.push(ev)
        break
      case 'loop_halt':
        // Keep the halt reason so MessageList/ChatPane can render the banner.
        currentChatState.halt_reason = (ev as LoopHaltEvent).reason
        currentChatState.toolEvents.push(ev)
        break
      case 'cost_update':
        // chatloop new shape: cny is cumulative spend (CNY). Keep using
        // cost_so_far as the displayed running total.
        currentChatState.cost_so_far = (ev as CostUpdateEvent).cny
        currentChatState.toolEvents.push(ev)
        break
      case 'done': {
        const e = ev as DoneEvent
        flushDraftAsMessage()
        currentChatState.streamingStatus = 'idle'
        currentChatState.streaming_phase = 'idle'
        // Plan 3 Task 7: terminal event → clear in-flight task tracker
        currentChatState.active_task_id = null
        currentChatState.loop_progress = null
        // Preserve halt_reason banner only when the turn ended non-naturally.
        // stop_reason missing (field absent) → keep existing halt_reason so a
        // prior loop_halt banner is not silently erased by an incomplete done event.
        if (e.stop_reason === 'natural') {
          currentChatState.halt_reason = null
        } else if (e.stop_reason) {
          currentChatState.halt_reason = e.stop_reason
        }
        // stop_reason absent → leave halt_reason unchanged
        currentChatState.toolEvents.push(e)
        break
      }
      case 'error':
        currentChatState.streamingStatus = 'error'
        currentChatState.streaming_phase = 'error'
        currentChatState.errorMessage = (ev as ErrorEvent).error
        // Plan 3 Task 7: terminal event → clear in-flight task tracker
        currentChatState.active_task_id = null
        currentChatState.loop_progress = null
        currentChatState.toolEvents.push(ev as ErrorEvent)
        break
      default:
        currentChatState.toolEvents.push(ev)
    }
  },
  /** Reset UI to idle regardless of current streaming state.
   *
   * Called by useChatSSE abort() and cancelTask() so that any UI-initiated
   * stop (abort fallback or explicit cancel) always brings the UI back to a
   * usable idle state — even if the active_task_id was never set (POST still
   * pending) or if the backend never sent a terminal done/error frame.
   */
  resetStreaming() {
    currentChatState.streamingStatus = 'idle'
    currentChatState.active_task_id = null
    currentChatState.streaming_phase = 'idle'
    currentChatState.streaming_phase_label = undefined
    currentChatState.streamingDraft = ''
    currentChatState.errorMessage = null
    currentChatState.loop_progress = null
    currentChatState.halt_reason = null
    currentChatState.dispatchLanes = []
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
    currentChatState.loop_progress = INITIAL.loop_progress
    currentChatState.halt_reason = INITIAL.halt_reason
    currentChatState.dispatchLanes = []
    paperTradingActions.reset()
  },
}
