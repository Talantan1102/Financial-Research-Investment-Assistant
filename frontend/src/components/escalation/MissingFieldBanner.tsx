import { ExclamationCircleOutlined } from '@ant-design/icons'
import { Alert, List, Tag, Typography } from 'antd'
import type { MissingFieldHint, MissingFieldReason } from '@/types/escalation'

const REASON_COLOR: Record<MissingFieldReason, string> = {
  llm_uncertain: 'orange',
  schema_required_but_empty: 'red',
  user_skipped: 'default',
}

export interface MissingFieldBannerProps {
  hints: readonly MissingFieldHint[]
}

export function MissingFieldBanner({ hints }: MissingFieldBannerProps) {
  if (hints.length === 0) return null
  return (
    <Alert
      type="warning"
      icon={<ExclamationCircleOutlined />}
      message={<>⚠️ {hints.length} 个字段需要你的确认 / 补充</>}
      description={
        <List
          size="small"
          dataSource={[...hints]}
          renderItem={(h) => (
            <List.Item key={h.field_path}>
              <Tag color={REASON_COLOR[h.reason]}>{h.reason}</Tag>
              <Typography.Text code>{h.field_path}</Typography.Text>
              <Typography.Text>{h.llm_question_for_user}</Typography.Text>
            </List.Item>
          )}
        />
      }
      style={{ marginBottom: 12 }}
    />
  )
}
