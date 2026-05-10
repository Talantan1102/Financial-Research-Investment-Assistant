import { Card, Empty, Space, Spin, Table, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listReports, type ResearchReportSummary } from '@/api/reportsApi'
import ReportDetailModal from './ReportDetailModal'

export function ReportsListPage() {
  const [items, setItems] = useState<ResearchReportSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [openId, setOpenId] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    listReports()
      .then((rows) => {
        if (alive) setItems(rows)
      })
      .catch(() => {})
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  if (loading) return <div style={{ padding: 40, textAlign: 'center' }}><Spin /></div>
  if (items.length === 0) return <Empty description="暂无研报" />

  return (
    <Card title="研究报告" extra={<span>{items.length} 份</span>} style={{ margin: 16 }}>
      <Table<ResearchReportSummary>
        rowKey="id"
        dataSource={items}
        pagination={{ pageSize: 20 }}
        onRow={(r) => ({ onClick: () => setOpenId(r.id) })}
        columns={[
          { title: '标题', dataIndex: 'title' },
          {
            title: '生成时间',
            dataIndex: 'created_at',
            render: (v: string) => new Date(v).toLocaleString(),
          },
          {
            title: '成本',
            dataIndex: 'cost_usd',
            render: (v: number) => <Tag color="blue">${v.toFixed(3)}</Tag>,
          },
          {
            title: '来源',
            dataIndex: 'source_chat_session_id',
            render: (sid: string | null) =>
              sid ? (
                <Space onClick={(e) => e.stopPropagation()}>
                  <Link to={`/chat/${sid}`}>回到 chat</Link>
                </Space>
              ) : (
                <Tag>独立</Tag>
              ),
          },
        ]}
      />
      {openId ? <ReportDetailModal id={openId} onClose={() => setOpenId(null)} /> : null}
    </Card>
  )
}

export default ReportsListPage
