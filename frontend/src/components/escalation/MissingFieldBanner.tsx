import { Alert } from 'antd'
import type { MissingFieldHint } from '@/types/escalation'

export function MissingFieldBanner({ hints }: { hints: readonly MissingFieldHint[] }) {
  if (hints.length === 0) return null
  return (
    <div style={{ marginBottom: 12 }}>
      {hints.map((h) => (
        <Alert
          key={h.field_path}
          message={h.llm_question_for_user}
          type="warning"
          showIcon
          style={{ marginBottom: 6 }}
        />
      ))}
    </div>
  )
}
