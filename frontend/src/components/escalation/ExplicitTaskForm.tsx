import { Form, Input } from 'antd'
import type { ExplicitTask } from '@/types/escalation'
import { InlineEditField } from './InlineEditField'

export interface ExplicitTaskFormProps {
  value: Readonly<ExplicitTask>
}

export function ExplicitTaskForm({ value }: ExplicitTaskFormProps) {
  return (
    <Form layout="vertical">
      <Form.Item label="原始最后用户问句">
        <Input value={value.raw_last_user_turn} readOnly />
      </Form.Item>
      <Form.Item label="抽取意图">
        <InlineEditField fieldPath="explicit_task.extracted_intent" llmValue={value.extracted_intent} />
      </Form.Item>
      <Form.Item label="目标 ts_code">
        <InlineEditField fieldPath="explicit_task.target_ts_code" llmValue={value.target_ts_code} />
      </Form.Item>
      <Form.Item label="目标实体名">
        <InlineEditField fieldPath="explicit_task.target_entity_name" llmValue={value.target_entity_name} />
      </Form.Item>
      <Form.Item label="用户附加说明">
        <InlineEditField
          fieldPath="explicit_task.user_extra_message"
          llmValue={value.user_extra_message}
          multiline
        />
      </Form.Item>
    </Form>
  )
}
