/**
 * frontend/src/pages/portfolio/index.tsx
 *
 * 持仓总览页 — GET /portfolio/positions 真接后端。
 *
 * 实现程度:
 *  - 持仓列表表格:ts_code / 名称 / 数量 / 均价 / 总成本 / 已实现盈亏 / 最新行情价 / 静默标记
 *  - 错误 fail-loud:400/401/5xx 都显示错误提示,不静默降级为空态
 *
 * TODO (后端暂未暴露 GET /portfolio/trades):
 *  - 交易记录列表 — 等 backend 添加 GET /portfolio/trades 后 wire 入 listTrades()
 *  - Onboarding 表单 — POST /portfolio/onboarding 批量录入初始持仓
 */

import { Alert, Card, Spin, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useState } from 'react'
import { listPositions, type PositionRead } from '@/api/portfolio'

const { Text } = Typography

const columns: ColumnsType<PositionRead> = [
  {
    title: '代码',
    dataIndex: 'ts_code',
    key: 'ts_code',
    width: 110,
    render: (v: string) => (
      <Text
        style={{
          fontFamily: '"SF Mono", "JetBrains Mono", Consolas, monospace',
          fontSize: 13,
          fontWeight: 500,
        }}
      >
        {v}
      </Text>
    ),
  },
  {
    title: '名称',
    dataIndex: 'name',
    key: 'name',
    width: 120,
  },
  {
    title: '持仓量',
    dataIndex: 'quantity',
    key: 'quantity',
    width: 90,
    align: 'right',
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: '均价 (¥)',
    dataIndex: 'avg_cost',
    key: 'avg_cost',
    width: 100,
    align: 'right',
    render: (v: string) => parseFloat(v).toFixed(3),
  },
  {
    title: '总成本 (¥)',
    dataIndex: 'total_cost',
    key: 'total_cost',
    width: 110,
    align: 'right',
    render: (v: string) => parseFloat(v).toFixed(2),
  },
  {
    title: '已实现盈亏 (¥)',
    dataIndex: 'realized_pnl',
    key: 'realized_pnl',
    width: 130,
    align: 'right',
    render: (v: string) => {
      const n = parseFloat(v)
      const color = n > 0 ? '#27875a' : n < 0 ? '#c0392b' : undefined
      return <span style={{ color, fontWeight: n !== 0 ? 500 : undefined }}>{n.toFixed(2)}</span>
    },
  },
  {
    title: '最新行情 (¥)',
    dataIndex: 'last_quote_price',
    key: 'last_quote_price',
    width: 120,
    align: 'right',
    render: (v: string | null) =>
      v != null ? parseFloat(v).toFixed(3) : <Text type="secondary">—</Text>,
  },
  {
    title: '静默',
    dataIndex: 'is_silenced',
    key: 'is_silenced',
    width: 80,
    align: 'center',
    render: (v: boolean) =>
      v ? <Tag color="default">静默</Tag> : <Tag color="success">监控中</Tag>,
  },
]

export default function PortfolioPage() {
  const [positions, setPositions] = useState<PositionRead[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    listPositions()
      .then((res) => {
        if (!alive) return
        setPositions(res.data)
      })
      .catch((err: unknown) => {
        if (!alive) return
        const msg = err instanceof Error ? err.message : String(err)
        setError(msg)
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <Alert
          type="error"
          showIcon
          message="加载持仓失败"
          description={error}
        />
      </div>
    )
  }

  return (
    <div style={{ padding: 16 }}>
      <Card
        title="持仓总览"
        extra={<Text type="secondary">{positions.length} 只</Text>}
      >
        <Table<PositionRead>
          rowKey="id"
          dataSource={positions}
          columns={columns}
          pagination={{ pageSize: 20 }}
          size="small"
          locale={{ emptyText: '暂无持仓 — 通过 /portfolio/onboarding 批量录入初始仓位' }}
        />
      </Card>

      {/* TODO: 交易记录 — 等后端暴露 GET /portfolio/trades 后在此展示 */}
    </div>
  )
}
