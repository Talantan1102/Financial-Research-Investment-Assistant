import type { ChatMessage } from '@/types/chat'
export function SystemMessage({ message }: { message: ChatMessage }) {
  return <div data-testid={`sys-msg-${message.id}`}>{message.content}</div>
}
