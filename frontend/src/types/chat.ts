/**
 * frontend/src/types/chat.ts
 *
 * SSE event payload types + Chat REST DTOs. Mirrors backend Plan 1 Pydantic
 * schemas. Each event has a monotonic `seq` field used by SSE reconnect (F6)
 * and cross-chat ordering (F8).
 */

import type { EscalationPacket } from './escalation'

export type MessageType = 'text' | 'tool_call' | 'tool_result' | 'research_report' | 'escalation' | 'system' | 'chart'

export interface ToolCallData {
  tool_name: string
  tool_args: Record<string, unknown>
  status: 'running' | 'success' | 'error'
  result_summary?: string
  error_message?: string
  // chatloop tool_error{hint}: actionable guidance shown alongside the error.
  error_hint?: string
  // chatloop tool_end{cached}: result served from the tool-result cache → ⚡ badge.
  cached?: boolean
  started_at: string
  ended_at?: string
}

export interface ChartSpec {
  type: 'echarts'
  option: Record<string, unknown>
}

// run_python 产出的 plotly 交互图(经 chart SSE 事件旁路渲染,figure 不进 LLM 上下文)。
export interface PlotlyFigure {
  data: Record<string, unknown>[]
  layout?: Record<string, unknown>
}

export interface PlotlySpec {
  type: 'plotly'
  figure: PlotlyFigure
}

export interface BaseEvent {
  seq: number
}

export interface TokenEvent extends BaseEvent {
  type: 'token'
  // chatloop backend payload carries both `text` and `content` (same value);
  // `content` is the historical frontend field. `text` kept optional for
  // direct backend-shape consumers / tests.
  content: string
  text?: string
}

export interface ReasoningEvent extends BaseEvent {
  type: 'reasoning'
  text: string
}

export interface StepStartEvent extends BaseEvent {
  type: 'step_start'
  step: number
  max_steps: number
}

// chatloop emits `tool_call` twice with two shapes:
//  - loop stream delta: { tool_name }  (name only, args not yet assembled)
//  - hub pre-dispatch:   { tool, args } (full args, replaces the old plan event)
// Both fields optional so the union accepts either; renderers prefer `tool`.
export interface ToolCallEvent extends BaseEvent {
  type: 'tool_call'
  tool?: string
  tool_name?: string
  args?: Record<string, unknown>
}

export interface ToolStartEvent extends BaseEvent {
  type: 'tool_start'
  tool: string
}

export interface ToolEndEvent extends BaseEvent {
  type: 'tool_end'
  tool: string
  digest?: string
  cached?: boolean
}

export interface ToolErrorEvent extends BaseEvent {
  type: 'tool_error'
  tool: string
  error: string
  hint?: string
}

// chatloop run_python 产图:每张 figure 一帧,旁路渲染成独立 chart 消息。
export interface ChartEvent extends BaseEvent {
  type: 'chart'
  chart_id: string
  figure: PlotlyFigure
}

export interface SteerMergedEvent extends BaseEvent {
  type: 'steer_merged'
  preview: string
}

export interface LoopHaltEvent extends BaseEvent {
  type: 'loop_halt'
  reason: string
}

export interface SkillLoadEvent extends BaseEvent {
  type: 'skill_load'
  skill_name: string
  level: 'L1' | 'L2' | 'L3a' | 'L3b'
}

export interface EscalateRequestEvent extends BaseEvent {
  type: 'escalate_request'
  reason: string
}

export interface EscalatePacketDraftEvent extends BaseEvent {
  type: 'escalate_packet_draft'
  packet: EscalationPacket
}

export interface ResearchPlannerDoneEvent extends BaseEvent {
  type: 'research_planner_done'
  plan: unknown
}

export interface ResearchToolStartEvent extends BaseEvent {
  type: 'research_tool_start'
  tool_name: string
  tool_args: Record<string, unknown>
  call_id: string
}

export interface ResearchToolEndEvent extends BaseEvent {
  type: 'research_tool_end'
  call_id: string
  result: unknown
}

export interface ResearchAnalystDoneEvent extends BaseEvent {
  type: 'research_analyst_done'
  summary: string
}

export interface ResearchWriterDoneEvent extends BaseEvent {
  type: 'research_writer_done'
  draft_summary: string
}

export interface ResearchCriticDoneEvent extends BaseEvent {
  type: 'research_critic_done'
  score: number
}

export interface EscalateDoneEvent extends BaseEvent {
  type: 'escalate_done'
  research_report_id: string
}

export interface EscalateErrorEvent extends BaseEvent {
  type: 'escalate_error'
  error: string
}

export interface CostUpdateEvent extends BaseEvent {
  type: 'cost_update'
  // chatloop backend shape (spec § 5.1): cumulative CNY spend + token totals +
  // cache-hit token count (first-class cache metric).
  cny: number
  tokens: number
  cached_tokens: number
}

export interface DoneEvent extends BaseEvent {
  type: 'done'
  // chatloop sets stop_reason: natural | max_steps | budget | spinning | ...
  stop_reason?: string
}

export interface ErrorEvent extends BaseEvent {
  type: 'error'
  error: string
}

export type SSEEvent =
  | TokenEvent
  | ReasoningEvent
  | StepStartEvent
  | ToolCallEvent
  | ToolStartEvent
  | ToolEndEvent
  | ToolErrorEvent
  | ChartEvent
  | SteerMergedEvent
  | LoopHaltEvent
  | SkillLoadEvent
  | EscalateRequestEvent
  | EscalatePacketDraftEvent
  | ResearchPlannerDoneEvent
  | ResearchToolStartEvent
  | ResearchToolEndEvent
  | ResearchAnalystDoneEvent
  | ResearchWriterDoneEvent
  | ResearchCriticDoneEvent
  | EscalateDoneEvent
  | EscalateErrorEvent
  | CostUpdateEvent
  | DoneEvent
  | ErrorEvent

export type SSEEventType = SSEEvent['type']

export interface ChatSession {
  id: string
  user_id?: string | null
  title: string
  created_at?: string
  updated_at: string
  message_count: number
  last_msg_preview: string | null
}

// Plan 3 Task 5: chat_messages.status — done|partial|cancelled|error。
// Frontend uses this to gate retry button rendering (only on partial / error).
export type ChatMessageStatus = 'done' | 'partial' | 'cancelled' | 'error'

export interface ChatMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'tool' | 'system'
  content: string
  message_type: MessageType
  tool_call_data: Record<string, unknown> | null
  research_report_id: string | null
  research_report_summary: string | null
  created_at: string
  // Plan 3 Task 7: backend GET /chats/{sid} 已返 task_id + status per message
  // (router/chats.py)。前端用以渲染 retry button(error/partial 后)。
  // 老消息可能为 null/缺失 — optional 即可。
  task_id?: string | null
  status?: ChatMessageStatus
  // run_python 产出的交互图(message_type='chart');由 chart SSE 事件构造的本地消息携带。
  chart_spec?: PlotlySpec
}

export interface ChatDetail {
  session: ChatSession
  messages: ChatMessage[]
  // Plan 2 Task 7: backend GET /chats/{sid} 返回当前 in-flight chat_task UUID
  // (queued/running 状态),否则 null。前端切回 session 时用这字段 subscribe
  // in-flight stream — Spec § 5.2 Scenario B 核心。
  active_task_id?: string | null
}

export interface CreateChatRequest {
  title?: string
}

export interface SendChatMessageRequest {
  session_id: string
  content: string
  forced_tool_name?: string
  forced_tool_args?: Record<string, unknown>
}
