import { List, Tag } from 'antd'
import type { KnownFacts } from '@/types/escalation'

export interface KnownFactsFormProps {
  value: Readonly<KnownFacts>
}

export function KnownFactsForm({ value }: KnownFactsFormProps) {
  if (value.tool_results.length === 0) {
    return <p>无已知工具结果</p>
  }
  return (
    <List
      size="small"
      dataSource={[...value.tool_results]}
      renderItem={(t) => (
        <List.Item key={t.cache_id}>
          <List.Item.Meta
            title={
              <span>
                <Tag color="blue">{t.tool_name}</Tag>
                <span style={{ color: 'rgba(0,0,0,0.45)', fontSize: 12 }}>
                  {t.cached_at}
                </span>
              </span>
            }
            description={
              <div>
                <pre style={{ fontSize: 11, color: 'rgba(0,0,0,0.65)', margin: 0 }}>
                  args: {JSON.stringify(t.tool_args)}
                </pre>
                <pre style={{ fontSize: 12, marginTop: 4 }}>{t.result_summary}</pre>
              </div>
            }
          />
        </List.Item>
      )}
    />
  )
}
