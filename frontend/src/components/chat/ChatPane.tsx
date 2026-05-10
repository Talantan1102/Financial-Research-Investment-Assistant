import { useCallback } from 'react'
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
import styles from '@/styles/chat.module.scss'

export interface ChatPaneProps {
  sessionId?: string
}

export function ChatPane({ sessionId: sessionIdProp }: ChatPaneProps = {}) {
  const params = useParams<{ session_id: string }>()
  const sessionId = sessionIdProp ?? params.session_id ?? null
  const snap = useSnapshot(currentChatState)
  const messages = useDeferredMessages(snap.messages ?? [])
  const sse = useChatSSE({ sessionId })

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

  const empty = messages.length === 0
  return (
    <div className={styles.chatPane}>
      <CostMeter />
      <section role="region" aria-label="messages" className={styles.messagesRegion}>
        {empty ? (
          <div className={styles.emptyState}>开始一个新对话 — 试试问 "工商银行现价多少?"</div>
        ) : (
          <MessageList messages={[...messages]} onContinueAsk={onContinueAsk} />
        )}
        <StreamingIndicator />
      </section>
      <section role="region" aria-label="input" className={styles.inputRegion}>
        <InputArea
          sessionId={sessionId ?? undefined}
          onSend={onSend}
          onAbort={onAbort}
          onEscalate={onEscalate}
        />
      </section>
    </div>
  )
}
