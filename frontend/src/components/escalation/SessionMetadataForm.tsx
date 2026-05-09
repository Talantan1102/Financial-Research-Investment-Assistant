import type { SessionMetadata } from '@/types/escalation'

export interface SessionMetadataFormProps {
  value: Readonly<SessionMetadata>
}

export function SessionMetadataForm({ value }: SessionMetadataFormProps) {
  return (
    <div data-testid="session-metadata-form">
      <p>chat_session_id: {value.chat_session_id}</p>
      <p>chat_turn_count: {value.chat_turn_count}</p>
    </div>
  )
}
