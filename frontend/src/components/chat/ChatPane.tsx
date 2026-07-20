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

function safeRequestJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? '无法显示请求详情'
  } catch {
    return '无法显示请求详情'
  }
}

function inputRequestText(request: Record<string, unknown>): string {
  for (const key of ['question', 'message', 'prompt', 'instruction']) {
    const value = request[key]
    if (typeof value === 'string' && value.trim()) return value
  }
  return safeRequestJson(request)
}

interface ApprovalItem {
  key: string
  name: string
  arguments: unknown
  executionId?: string
  semanticKey?: string
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function approvalItems(request: Record<string, unknown>): ApprovalItem[] {
  const items: ApprovalItem[] = []
  if (Array.isArray(request.tool_calls)) {
    for (const rawCall of request.tool_calls) {
      const call = asRecord(rawCall)
      if (!call) continue
      const name = typeof call.name === 'string' ? call.name : '未知工具'
      const id = typeof call.id === 'string' ? call.id : `${items.length}`
      items.push({ key: `call-${id}`, name, arguments: call.arguments })
    }
  }
  if (Array.isArray(request.execution_bindings)) {
    for (const rawBinding of request.execution_bindings) {
      const binding = asRecord(rawBinding)
      const call = asRecord(binding?.tool_call)
      if (!binding || !call) continue
      const name = typeof call.name === 'string' ? call.name : '未知工具'
      const executionId = typeof binding.execution_id === 'string' ? binding.execution_id : undefined
      const semanticKey = typeof binding.semantic_key === 'string' ? binding.semantic_key : undefined
      items.push({
        key: `binding-${executionId ?? items.length}`,
        name,
        arguments: call.arguments,
        executionId,
        semanticKey,
      })
    }
  }
  return items
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
  const ownsSessionState = sessionId === null || chatSnap.session_id === sessionId
  const messages = useDeferredMessages(ownsSessionState ? chatSnap.messages ?? [] : [])

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

  const pendingMessage = ownsSessionState && chatSnap.streamingDraft
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
  const pendingApprovals = run.pause?.type === 'approval_request'
    ? approvalItems(run.pause.request)
    : []

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
              {pendingApprovals.length > 0 ? (
                <ul>
                  {pendingApprovals.map((item) => (
                    <li key={item.key}>
                      <strong>{item.name}</strong>
                      <pre>{safeRequestJson(item.arguments)}</pre>
                      {item.executionId ? <div>执行绑定：{item.executionId}</div> : null}
                      {item.semanticKey ? <div>语义绑定：{item.semanticKey}</div> : null}
                    </li>
                  ))}
                </ul>
              ) : <pre>{safeRequestJson(run.pause.request)}</pre>}
              <button type="button" onClick={() => { void run.resumeRun({ approved: true }) }}>全部批准</button>
              <button type="button" onClick={() => { void run.resumeRun({ approved: false }) }}>全部拒绝</button>
            </div>
          ) : null}
          {run.pause?.type === 'input_request' ? (
            <div role="region" aria-label="补充信息请求">
              <p>{inputRequestText(run.pause.request)}</p>
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
