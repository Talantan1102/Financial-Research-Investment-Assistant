import { memo, useMemo } from 'react'
import type { ChatMessage } from '@/types/chat'
import { renderMarkdown } from '@/utils/markdown'
import styles from '@/styles/markdown.module.scss'

export interface TextMessageProps {
  message: ChatMessage
}

function TextMessageInner({ message }: TextMessageProps) {
  const html = useMemo(() => renderMarkdown(message.content), [message.content])
  return (
    <div
      data-role={message.role}
      data-testid={`text-msg-${message.id}`}
      className={`${styles.markdownBody} ${message.role === 'user' ? styles.user : styles.assistant}`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

export const TextMessage = memo(
  TextMessageInner,
  (prev, next) =>
    prev.message.content === next.message.content &&
    prev.message.role === next.message.role,
)
