import { useState } from 'react'
import { Col, Row, Tabs } from 'antd'
import type { TabsProps } from 'antd'
import { MemoryWorkingBlocks } from './components/MemoryWorkingBlocks'

/**
 * /memory page shell — Plan 7A.
 *
 * 三 tab(Graph / Timeline / Audit)+ 右栏 working blocks always-visible.
 * tab 内容此 plan 留 placeholder div, 由 Plan 7B 替换为 MemoryGraph /
 * MemoryTimeline / MemoryAuditLog 真实组件。
 *
 * spec § 9 + shared contracts § 10
 */
export default function MemoryPage() {
  const [activeKey, setActiveKey] = useState<string>('graph')

  const tabs: TabsProps['items'] = [
    {
      key: 'graph',
      label: <span data-testid="memory-tab-graph">Graph</span>,
      children: (
        <div
          data-testid="memory-graph-placeholder"
          style={{ minHeight: 480, padding: 24, color: '#8a96a3' }}
        >
          Graph view (Plan 7B 实现 Cytoscape 可视化)
        </div>
      ),
    },
    {
      key: 'timeline',
      label: <span data-testid="memory-tab-timeline">Timeline</span>,
      children: (
        <div
          data-testid="memory-timeline-placeholder"
          style={{ minHeight: 480, padding: 24, color: '#8a96a3' }}
        >
          Timeline view (Plan 7B 实现 horizontal bar + valid_from 排序)
        </div>
      ),
    },
    {
      key: 'audit',
      label: <span data-testid="memory-tab-audit">Audit</span>,
      children: (
        <div
          data-testid="memory-audit-placeholder"
          style={{ minHeight: 480, padding: 24, color: '#8a96a3' }}
        >
          Audit log (Plan 7B 实现 invalidated edges 列表 + 一键否决)
        </div>
      ),
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
