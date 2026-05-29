/**
 * frontend/src/pages/reports/index.tsx
 *
 * Reports list page at /reports.
 *
 * FIXED (bugs 1-3):
 *  - Was importing from @/api/reportsApi (raw fetch, /api/v0/reports, wrong schema).
 *  - Now imports from @/api/reports (axios request client, /reports, correct schema).
 *  - Fields aligned to backend ReportListItem: target_name, cost, investment_recommendation.
 *  - Fail-loud: errors are surfaced via antd message.error, not silently swallowed.
 */
import { Card, Empty, Spin, Table, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { listReports, type ReportListItem } from '@/api/reports'
import ReportDetailModal from './ReportDetailModal'

export function ReportsListPage() {
  const [items, setItems] = useState<ReportListItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    listReports(1, 100)
      .then((res) => {
        if (!alive) return
        setItems(res.data.items)
        setTotal(res.data.total)
      })
      .catch((err: unknown) => {
        if (!alive) return
        const msg =
          err instanceof Error ? err.message : String(err)
        setError(msg)
        void window.$app.message.error(`加载研报列表失败: ${msg}`)
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  if (loading) return <div style={{ padding: 40, textAlign: 'center' }}><Spin /></div>

  if (error) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#cf1322' }}>
        加载失败: {error}
      </div>
    )
  }

  if (items.length === 0) return <Empty description="暂无研报" />

  return (
    <Card title="研究报告" extra={<span>{total} 份</span>} style={{ margin: 16 }}>
      <Table<ReportListItem>
        rowKey="id"
        dataSource={items}
        pagination={{ pageSize: 20 }}
        onRow={(r) => ({ onClick: () => setOpenId(r.id) })}
        columns={[
          { title: '目标', dataIndex: 'target_name' },
          {
            title: '生成时间',
            dataIndex: 'created_at',
            render: (v: string) => new Date(v).toLocaleString(),
          },
          {
            title: '成本',
            dataIndex: 'cost',
            render: (v?: number) => (
              <Tag color="blue">¥{(v ?? 0).toFixed(2)}</Tag>
            ),
          },
          {
            title: '状态',
            dataIndex: 'status',
            render: (s: string) => {
              const colorMap: Record<string, string> = {
                completed: 'green',
                streaming: 'blue',
                failed: 'red',
              }
              return <Tag color={colorMap[s] ?? 'default'}>{s}</Tag>
            },
          },
          {
            title: '投资建议',
            dataIndex: 'investment_recommendation',
            render: (rec: string | null) =>
              rec ? <Tag>{rec}</Tag> : <span>—</span>,
          },
        ]}
      />
      {openId ? <ReportDetailModal id={openId} onClose={() => setOpenId(null)} /> : null}
    </Card>
  )
}

export default ReportsListPage
