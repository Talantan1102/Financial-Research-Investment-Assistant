import { Empty, Form, Input, List, Progress, Space, Tag } from 'antd'
import type { ChatDerivedSignals, Entity, Preference } from '@/types/escalation'
import { InlineEditField } from './InlineEditField'

export interface ChatDerivedSignalsFormProps {
  value: Readonly<ChatDerivedSignals>
}

const ROLE_COLOR: Record<Entity['role'], string> = {
  primary_target: 'red',
  comparative_target: 'gold',
  mentioned_in_passing: 'default',
}

export function ChatDerivedSignalsForm({ value }: ChatDerivedSignalsFormProps) {
  return (
    <Form layout="vertical">
      <Form.Item label="实体">
        {value.entities.length === 0 ? (
          <Empty description="无" />
        ) : (
          <List
            size="small"
            dataSource={[...value.entities]}
            renderItem={(e, idx) => (
              <List.Item>
                <Space wrap>
                  <strong>{e.name}</strong>
                  <Tag>{e.ts_code ?? '?'}</Tag>
                  <Tag color={ROLE_COLOR[e.role]}>{e.role}</Tag>
                  <span style={{ color: 'rgba(0,0,0,0.45)' }}>
                    turns: {e.mention_turn_indices.join(',')}
                  </span>
                  <InlineEditField
                    fieldPath={`chat_derived_signals.entities[${idx}].name`}
                    llmValue={e.name}
                  />
                </Space>
              </List.Item>
            )}
          />
        )}
      </Form.Item>
      <Form.Item label="偏好">
        {value.preferences.length === 0 ? (
          <Empty description="无" />
        ) : (
          <List
            size="small"
            dataSource={[...value.preferences]}
            renderItem={(p: Preference, idx) => (
              <List.Item>
                <Space wrap>
                  <Tag color="purple">{p.category}</Tag>
                  <span>{p.text}</span>
                  <span style={{ color: 'rgba(0,0,0,0.45)' }}>
                    conf: {(p.confidence * 100).toFixed(0)}%
                  </span>
                  <InlineEditField
                    fieldPath={`chat_derived_signals.preferences[${idx}].text`}
                    llmValue={p.text}
                  />
                </Space>
              </List.Item>
            )}
          />
        )}
      </Form.Item>
      <Form.Item label="未解决问题">
        {value.open_questions.length === 0 ? (
          <Empty description="无" />
        ) : (
          <List
            size="small"
            dataSource={[...value.open_questions]}
            renderItem={(q) => <List.Item>{q}</List.Item>}
          />
        )}
      </Form.Item>
      <Form.Item label="推断 persona">
        <Input value={value.inferred_persona ?? ''} readOnly />
      </Form.Item>
      <Form.Item label="抽取置信度">
        <Progress percent={Math.round(value.extraction_confidence * 100)} />
      </Form.Item>
    </Form>
  )
}
