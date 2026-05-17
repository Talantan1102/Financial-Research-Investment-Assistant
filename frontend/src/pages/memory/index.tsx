import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Col, Row, Tabs } from 'antd'
import type { TabsProps } from 'antd'
import MemoryAuditLog from '@/components/memory/MemoryAuditLog'
import MemoryGraph from '@/components/memory/MemoryGraph'
import MemoryPersona from '@/components/memory/MemoryPersona'
import MemoryTimeline from '@/components/memory/MemoryTimeline'
import { MemoryWorkingBlocks } from './components/MemoryWorkingBlocks'

/**
 * /memory page shell — Plan 7A scaffold + Plan 7B 三视图组件挂载.
 *
 * 三 tab(Graph / Timeline / Audit) — Plan 7B Task 2 挂 Graph,
 * Task 3/4 挂 Timeline / Audit。右栏 working blocks 始终可见。
 *
 * `?highlight_edge=<edge_id>` query param: 由 chat TextMessage [查看](#mem-...)
 * 链接跳转传入, 由 MemoryGraph 高亮该 edge.
 *
 * spec § 9 + shared contracts § 10.
 */
export default function MemoryPage() {
  const [activeKey, setActiveKey] = useState<string>('persona')
  const [searchParams] = useSearchParams()
  const highlightEdge = searchParams.get('highlight_edge')

  const tabs: TabsProps['items'] = [
    {
      key: 'persona',
      label: <span data-testid="memory-tab-persona">画像</span>,
      children: <MemoryPersona />,
    },
    {
      key: 'graph',
      label: <span data-testid="memory-tab-graph">图谱</span>,
      children: <MemoryGraph highlightEdgeId={highlightEdge} />,
    },
    {
      key: 'timeline',
      label: <span data-testid="memory-tab-timeline">时间线</span>,
      children: <MemoryTimeline />,
    },
    {
      key: 'audit',
      label: <span data-testid="memory-tab-audit">历史</span>,
      children: <MemoryAuditLog />,
    },
  ]

  return (
    <div
      data-testid="memory-page"
      style={{ padding: 24, maxWidth: 1400, margin: '0 auto' }}
    >
      <h2 style={{ marginBottom: 16 }}>Memory</h2>
      <Row gutter={16}>
        <Col xs={24} lg={18}>
          <Tabs
            activeKey={activeKey}
            onChange={setActiveKey}
            items={tabs}
            data-testid="memory-tabs"
          />
        </Col>
        <Col xs={24} lg={6}>
          <MemoryWorkingBlocks />
        </Col>
      </Row>
    </div>
  )
}
