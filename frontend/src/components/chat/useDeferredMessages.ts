import { useDeferredValue } from 'react'
import type { ChatMessage } from '@/types/chat'

/**
 * Wraps the messages list in `useDeferredValue` so that high-frequency token
 * stream updates yield to user input (typing in `<InputArea>` / scroll).
 * F1 industry polish — at ~50 tokens/s, naive setState causes input lag.
 */
export function useDeferredMessages(
  messages: readonly ChatMessage[],
): readonly ChatMessage[] {
  return useDeferredValue(messages)
}
