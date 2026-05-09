import { Form, Input, InputNumber } from 'antd'
import type { SessionMetadata } from '@/types/escalation'

export interface SessionMetadataFormProps {
  value: Readonly<SessionMetadata>
}

export function SessionMetadataForm({ value }: SessionMetadataFormProps) {
  return (
    <Form layout="vertical">
      <Form.Item label="chat_session_id">
        <Input value={value.chat_session_id} readOnly />
      </Form.Item>
      <Form.Item label="对话轮次">
        <InputNumber value={value.chat_turn_count} readOnly />
      </Form.Item>
      <Form.Item label="对话历史摘要">
        <Input.TextArea
          value={value.chat_history_summary ?? ''}
          readOnly
          autoSize={{ minRows: 2, maxRows: 6 }}
        />
      </Form.Item>
    </Form>
  )
}
