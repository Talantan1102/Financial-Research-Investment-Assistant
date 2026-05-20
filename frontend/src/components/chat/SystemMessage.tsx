import type { ChatMessage } from '@/types/chat'
import styles from '@/styles/chat.module.scss'

export interface SystemMessageProps {
  message: ChatMessage
}

export function SystemMessage({ message }: SystemMessageProps) {
  return (
    <div className={styles.systemMsg} data-testid={`sys-msg-${message.id}`}>
      {message.content}
    </div>
  )
}
