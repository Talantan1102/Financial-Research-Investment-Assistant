import { useCallback, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useSnapshot } from 'valtio'
import { CostMeter } from './CostMeter'
import { InputArea } from './InputArea'
import { MessageList } from './MessageList'
import { StreamingIndicator } from './StreamingIndicator'
import { useDeferredMessages } from './useDeferredMessages'
import { useChatSSE } from '@/hooks/useChatSSE'
import { currentChatState } from '@/store/current-chat'
import { escalationState } from '@/store/escalation'
import { EmptyState } from '@/components/states/EmptyState'
import styles from '@/styles/chat.module.scss'

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
  const displayMessages = pendingMessage ? [...messages, pendingMessage] : messages

  const onSend = useCallback(
    (text: string) => {
      if (!sessionId) return
      void sse.sendMessage(text)
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
        </div>
        <StreamingIndicator />
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
