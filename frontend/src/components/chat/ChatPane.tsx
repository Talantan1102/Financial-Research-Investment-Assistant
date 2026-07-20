import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useSnapshot } from 'valtio'
import { CostMeter } from './CostMeter'
import { DispatchLanes } from './DispatchLanes'
import { InputArea } from './InputArea'
import { MessageList } from './MessageList'
import { StreamingIndicator } from './StreamingIndicator'
import { useDeferredMessages } from './useDeferredMessages'
import { useRunSSE } from '@/hooks/useRunSSE'
import { currentChatState } from '@/store/current-chat'
import { chatSessionsActions, chatSessionsState } from '@/store/chat-sessions'
import { escalationState } from '@/store/escalation'
import { EmptyState } from '@/components/states/EmptyState'
import styles from '@/styles/chat.module.scss'

const HALT_REASON_LABEL: Record<string, string> = {
  max_steps: '已达执行步数上限',
  budget: '已达预算上限',
  spinning: '检测到重复打转',
}

export interface ChatPaneProps {
  sessionId?: string
  tenantId?: string
  initialRunId?: string | null
  initialRunStatus?: import('@/api/runApi').RunStatus | null
  sessionLoading?: boolean
  initialPause?: import('@/hooks/useRunSSE').RunPause | null
}

export function ChatPane({ sessionId: sessionIdProp, tenantId: tenantIdProp, initialRunId, initialRunStatus, initialPause, sessionLoading = false }: ChatPaneProps = {}) {
  const params = useParams<{ session_id: string }>()
  const navigate = useNavigate()
  const sessionId = sessionIdProp ?? params.session_id ?? null
  const chatSnap = useSnapshot(currentChatState)
  const sessionsSnap = useSnapshot(chatSessionsState)
  const [resolvedTenantId, setResolvedTenantId] = useState<string | null>(
    tenantIdProp ?? sessionsSnap.tenant_id,
  )
  const [pauseInput, setPauseInput] = useState('')
  const messages = useDeferredMessages(chatSnap.messages ?? [])

  useEffect(() => {
    if (tenantIdProp) {
      setResolvedTenantId(tenantIdProp)
      return
    }
    let cancelled = false
    chatSessionsActions.resolveTenantId()
      .then((id) => { if (!cancelled) setResolvedTenantId(id) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [tenantIdProp])

  const run = useRunSSE({
    tenantId: resolvedTenantId,
    sessionId,
    initialRunId,
    initialRunStatus,
    initialPause,
    onSessionCreated: (createdSessionId) => {
      navigate(`/chat/${createdSessionId}`, { replace: true })
    },
  })

  const pendingMessage = chatSnap.streamingDraft
    ? {
        id: '__pending_assistant__',
        session_id: sessionId ?? '__pending__',
        role: 'assistant' as const,
        content: chatSnap.streamingDraft,
        message_type: 'text' as const,
        tool_call_data: null,
        research_report_id: null,
        research_report_summary: null,
        created_at: new Date().toISOString(),
      }
    : null
  const displayMessages = [...messages, ...(pendingMessage ? [pendingMessage] : [])]

  const onSend = useCallback((text: string) => {
    void run.sendPrompt(text)
  }, [run])
  const onEscalate = useCallback(() => {
    if (escalationState.packet_draft) return
  }, [])
  const onContinueAsk = useCallback(() => {
    document.querySelector<HTMLTextAreaElement>('[data-testid="input-textarea"]')?.focus()
  }, [])

  return (
    <div className={styles.chatPane}>
      <CostMeter />
      <section role="region" aria-label="messages" className={styles.messagesRegion}>
        <div className={styles.chatContainer}>
          {displayMessages.length === 0 ? (
            <EmptyState
              variant="chat-empty"
              title="开始一个新对话"
              description='试试问“工商银行现价多少？”'
            />
          ) : (
            <MessageList messages={displayMessages} onContinueAsk={onContinueAsk} />
          )}
          <DispatchLanes />
        </div>
        <StreamingIndicator />
        {chatSnap.halt_reason ? (
          <div className={styles.haltBanner} data-testid="loop-halt-banner" role="status">
            已达执行上限（{HALT_REASON_LABEL[chatSnap.halt_reason] ?? chatSnap.halt_reason}），以下基于已查信息
          </div>
        ) : null}
      </section>
      <section role="region" aria-label="input" className={styles.inputRegion}>
        <div className={styles.inputContainer}>
          <InputArea
            sessionId={sessionId ?? undefined}
            onSend={onSend}
            onEscalate={onEscalate}
            onCancel={() => { void run.cancelRun() }}
            blocked={resolvedTenantId === null || sessionLoading || run.pause !== null}
          />
          {run.pause?.type === 'approval_request' ? (
            <div role="region" aria-label="审批请求">
              <p>此操作需要你的审批</p>
              <button type="button" onClick={() => { void run.resumeRun({ approved: true }) }}>同意</button>
              <button type="button" onClick={() => { void run.resumeRun({ approved: false }) }}>拒绝</button>
            </div>
          ) : null}
          {run.pause?.type === 'input_request' ? (
            <div role="region" aria-label="补充信息请求">
              <label>
                补充信息
                <textarea aria-label="补充信息" value={pauseInput} onChange={(event) => setPauseInput(event.target.value)} />
              </label>
              <button
                type="button"
                disabled={!pauseInput.trim()}
                onClick={() => {
                  const text = pauseInput.trim()
                  if (!text) return
                  setPauseInput('')
                  void run.resumeRun({ text })
                }}
              >
                提交补充信息
              </button>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  )
}
