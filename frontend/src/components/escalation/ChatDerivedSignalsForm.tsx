import type { ChatDerivedSignals } from '@/types/escalation'

export interface ChatDerivedSignalsFormProps {
  value: Readonly<ChatDerivedSignals>
}

export function ChatDerivedSignalsForm({ value }: ChatDerivedSignalsFormProps) {
  return (
    <div data-testid="chat-derived-signals-form">
      <p>实体数: {value.entities.length}</p>
      <p>偏好数: {value.preferences.length}</p>
      <p>抽取信心: {value.extraction_confidence.toFixed(2)}</p>
    </div>
  )
}
