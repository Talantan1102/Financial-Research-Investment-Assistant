import type { ChatMessage } from '@/types/chat'

interface MessageListProps {
  messages: readonly ChatMessage[]
}

export function MessageList({ messages }: MessageListProps) {
  return (
    <div data-testid="message-list">
      {messages.map((m) => (
        <div key={m.id} style={{ padding: 8 }}>
          <strong>{m.role}: </strong>
          <span>{m.content}</span>
        </div>
      ))}
    </div>
  )
}
