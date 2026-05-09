import type { ChatMessage } from '@/types/chat'
export function ToolCallCard({ message }: { message: ChatMessage }) {
  const data = message.tool_call_data as Record<string, unknown> | null
  return <div data-testid={`tool-msg-${message.id}`}>tool: {String(data?.tool_name ?? '')}</div>
}
