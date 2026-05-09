import type { ChatMessage } from '@/types/chat'
export function TextMessage({ message }: { message: ChatMessage }) {
  return <div data-testid={`text-msg-${message.id}`}>{message.content}</div>
}
