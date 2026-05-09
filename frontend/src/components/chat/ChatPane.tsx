import { useSnapshot } from 'valtio'
import { useParams } from 'react-router-dom'
import { CostMeter } from './CostMeter'
import { InputArea } from './InputArea'
import { MessageList } from './MessageList'
import { StreamingIndicator } from './StreamingIndicator'
import { useDeferredMessages } from './useDeferredMessages'
import { currentChatState } from '@/store/current-chat'
import styles from '@/styles/chat.module.scss'

export interface ChatPaneProps {
  sessionId?: string
}

export function ChatPane({ sessionId: sessionIdProp }: ChatPaneProps = {}) {
  const params = useParams<{ session_id: string }>()
  const sessionId = sessionIdProp ?? params.session_id
  const snap = useSnapshot(currentChatState)
  const messages = useDeferredMessages(snap.messages ?? [])
  const empty = messages.length === 0
  return (
    <div className={styles.chatPane}>
      <CostMeter />
      <section role="region" aria-label="messages" className={styles.messagesRegion}>
        {empty ? (
          <div className={styles.emptyState}>开始一个新对话 — 试试问 "工商银行现价多少?"</div>
        ) : (
          <MessageList messages={[...messages]} />
        )}
        <StreamingIndicator />
      </section>
      <section role="region" aria-label="input" className={styles.inputRegion}>
        <InputArea sessionId={sessionId} />
      </section>
    </div>
  )
}
