import { useCallback, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useSnapshot } from 'valtio'
import { CostMeter } from './CostMeter'
import { DispatchLanes } from './DispatchLanes'
import { InputArea } from './InputArea'
import { MessageList } from './MessageList'
import { StreamingIndicator } from './StreamingIndicator'
import { useDeferredMessages } from './useDeferredMessages'
import { useChatSSE } from '@/hooks/useChatSSE'
import { currentChatState } from '@/store/current-chat'
import { escalationState } from '@/store/escalation'
import { EmptyState } from '@/components/states/EmptyState'
import type { ChatMessage, SteerMergedEvent } from '@/types/chat'
import styles from '@/styles/chat.module.scss'

// chatloop loop_halt reason → 用户可读的中文短语(spec § 1.3 撞闸种类)。
const HALT_REASON_LABEL: Record<string, string> = {
  max_steps: '已达执行步数上限',
  budget: '已达预算上限',
  spinning: '检测到重复打转',
}

function haltReasonLabel(reason: string): string {
  return HALT_REASON_LABEL[reason] ?? reason
}

export interface ChatPaneProps {
  sessionId?: string
  // Plan 2 Scenario B: 切 session 回来时,若 GET /chats/{sid} 返 active_task_id 非空,
  // 通过本 prop 传入,ChatPane 自动 subscribe in-flight stream(继续吐字)。
  activeTaskId?: string | null
}

export function ChatPane({
  sessionId: sessionIdProp,
  activeTaskId,
}: ChatPaneProps = {}) {
  const params = useParams<{ session_id: string }>()
  const sessionId = sessionIdProp ?? params.session_id ?? null
  const snap = useSnapshot(currentChatState)
  const messages = useDeferredMessages(snap.messages ?? [])
  const sse = useChatSSE({ sessionId })

  // Plan 2 dogfood Scenario B: activeTaskId 非空 → 自动 subscribe in-flight
  // stream。effect deps 仅含 activeTaskId,避免 sse 引用变更导致重复 subscribe。
  useEffect(() => {
    if (activeTaskId) {
      void sse.subscribeToTask(activeTaskId, '0')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTaskId])

  // Plan 2 dogfood fix: typewriter 通过 currentChatState.streamingDraft 一字字
  // push,但 ChatPane 之前只渲染 messages → 用户看不到打字机过程,只有 done
  // 后 flushDraftAsMessage 入 messages 才一次性显示。修补:streamingDraft 非
  // 空时插一条 pending assistant message,role/id 跟真 message 区分。
  const pendingMessage =
    snap.streamingDraft && sessionId
      ? {
          id: '__pending_assistant__',
          session_id: sessionId,
          role: 'assistant' as const,
          content: snap.streamingDraft,
          message_type: 'text' as const,
          tool_call_data: null,
          research_report_id: null,
          research_report_summary: null,
          created_at: new Date().toISOString(),
        }
      : null

  // Phase 5 Task 5.1: steer_merged 事件渲染为系统气泡("已并入指令: preview")。
  // 后端落库的插话 user 消息 turn 结束后会随历史 reload 出现;streaming 期间先用
  // 这些瞬时系统气泡给用户即时反馈(避免双气泡:历史 reload 走真消息,瞬时气泡只在
  // toolEvents 里,reload setSession 会清空 toolEvents)。
  const steerBubbles: ChatMessage[] = sessionId
    ? (snap.toolEvents as readonly { type: string }[])
        .filter((e): e is SteerMergedEvent => e.type === 'steer_merged')
        .map((e, i) => ({
          id: `__steer_merged_${i}__`,
          session_id: sessionId,
          role: 'system' as const,
          content: `已并入指令: ${e.preview}`,
          message_type: 'system' as const,
          tool_call_data: null,
          research_report_id: null,
          research_report_summary: null,
          created_at: new Date().toISOString(),
        }))
    : []

  const displayMessages = [
    ...messages,
    ...steerBubbles,
    ...(pendingMessage ? [pendingMessage] : []),
  ]

  const onSend = useCallback(
    (
      text: string,
      forced?: { forced_tool_name: string; forced_tool_args: Record<string, unknown> },
    ) => {
      if (!sessionId) return
      void sse.sendMessage(text, forced)
    },
    [sessionId, sse],
  )

  const onAbort = useCallback(() => sse.abort(), [sse])

  const onEscalate = useCallback(() => {
    // Plan 4b later tasks open EscalationConfirmDialog driven by escalationState
    if (escalationState.packet_draft) {
      // existing draft — leave phase as-is
      return
    }
  }, [])

  const onContinueAsk = useCallback((_id: string) => {
    const ta = document.querySelector<HTMLTextAreaElement>('[data-testid="input-textarea"]')
    ta?.focus()
  }, [])

  const empty = displayMessages.length === 0
  return (
    <div className={styles.chatPane}>
      <CostMeter />
      <section role="region" aria-label="messages" className={styles.messagesRegion}>
        <div className={styles.chatContainer}>
          {empty ? (
            <EmptyState
              variant="chat-empty"
              title="开始一个新对话"
              description='试试问 "工商银行现价多少?"'
            />
          ) : (
            <MessageList
              messages={[...displayMessages]}
              onContinueAsk={onContinueAsk}
              onRetry={sse.retryTask}
            />
          )}
          <DispatchLanes />
        </div>
        <StreamingIndicator />
        {snap.halt_reason ? (
          <div
            className={styles.haltBanner}
            data-testid="loop-halt-banner"
            role="status"
          >
            已达执行上限（{haltReasonLabel(snap.halt_reason)}），以下基于已查信息
          </div>
        ) : null}
      </section>
      <section role="region" aria-label="input" className={styles.inputRegion}>
        <div className={styles.inputContainer}>
          <InputArea
            sessionId={sessionId ?? undefined}
            onSend={onSend}
            onAbort={onAbort}
            onEscalate={onEscalate}
            onCancel={sse.cancelTask}
          />
        </div>
      </section>
    </div>
  )
}
