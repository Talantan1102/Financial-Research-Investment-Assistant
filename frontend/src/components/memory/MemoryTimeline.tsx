/**
 * MemoryTimeline (Plan 7B Task 3) — horizontal timeline view of /memory page.
 *
 * 横轴 valid_from → valid_to (or now), edge bar 颜色按 rel_type, hover Tooltip
 * 显 properties. 支持 rel_type 选择 + entity 关键字筛.
 *
 * 决策: 不引第三方 timeline 库 (vis-timeline / react-calendar-timeline 都
 * 200KB+, 单视图浪费). 纯 SVG/CSS + dayjs.
 *
 * Source spec § 9 视图 2, contracts § 10 fetchMemoryTimeline endpoint.
 */
import { Empty, Input, Select, Spin, Tag, Tooltip } from 'antd'
import dayjs from 'dayjs'
import { useEffect, useMemo, useState } from 'react'
import { fetchMemoryTimeline } from '@/api/memoryApi'
import type { TimelineEdge } from '@/types/memory'
import { classifyEdgeStatus, REL_TYPE_LABELS } from './MemoryGraph.styles'

const REL_COLORS: Record<string, string> = {
  HOLDS: '#52c41a',
  SOLD: '#ff4d4f',
  WATCHES: '#1890ff',
  PREFERS: '#13c2c2',
  AVOIDS: '#faad14',
  EXPRESSED_VIEW: '#722ed1',
  STUDIED: '#eb2f96',
  COMPARED: '#fa541c',
  BELONGS_TO: '#bfbfbf',
  HAS_CONCEPT: '#8c8c8c',
  CORRELATED_WITH: '#595959',
}

export default function MemoryTimeline() {
  const [edges, setEdges] = useState<TimelineEdge[]>([])
  const [loading, setLoading] = useState(true)
  const [filterRel, setFilterRel] = useState<string | null>(null)
  const [filterEntity, setFilterEntity] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchMemoryTimeline()
      .then((data) => {
        if (!cancelled) setEdges(data.items)
      })
      .catch(() => {
        /* leave empty */
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = useMemo(() => {
    return edges.filter((e) => {
      if (filterRel && e.rel_type !== filterRel) return false
      if (filterEntity) {
        const q = filterEntity.toLowerCase()
        if (
          !e.source_label.toLowerCase().includes(q) &&
          !e.target_label.toLowerCase().includes(q)
        )
          return false
      }
      return true
    })
  }, [edges, filterRel, filterEntity])

  const { minDate, maxDate } = useMemo(() => {
    if (filtered.length === 0) {
      return {
        minDate: dayjs().subtract(1, 'year'),
        maxDate: dayjs(),
      }
    }
    let min = dayjs(filtered[0].valid_from)
    let max = dayjs()
    filtered.forEach((e) => {
      const start = dayjs(e.valid_from)
      const end = e.valid_to ? dayjs(e.valid_to) : dayjs()
      if (start.isBefore(min)) min = start
      if (end.isAfter(max)) max = end
    })
    return { minDate: min, maxDate: max }
  }, [filtered])

  if (loading)
    return (
      <div data-testid="memory-timeline-loading" style={{ padding: 24 }}>
        <Spin size="large" />
      </div>
    )

  if (edges.length === 0)
    return (
      <Empty
        data-testid="memory-timeline-empty"
        description="还没有时间序列 — 先聊几条试试"
      />
    )

  const totalDays = Math.max(1, maxDate.diff(minDate, 'day'))
  const ROW_HEIGHT = 32
  const BAR_HEIGHT = 18

  return (
    <div data-testid="memory-timeline">
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center' }}>
        <Select
          allowClear
          placeholder="按关系类型筛"
          style={{ width: 180 }}
          value={filterRel}
          onChange={(v) => setFilterRel(v ?? null)}
          options={Object.entries(REL_TYPE_LABELS).map(([k, v]) => ({
            value: k,
            label: v,
          }))}
          data-testid="timeline-filter-rel"
        />
        <Input
          placeholder="按实体名筛(如 茅台)"
          style={{ width: 200 }}
          value={filterEntity}
          onChange={(e) => setFilterEntity(e.target.value)}
          allowClear
          data-testid="timeline-filter-entity"
        />
        <span data-testid="timeline-count">{filtered.length} 条</span>
      </div>

      <div
        data-testid="timeline-canvas"
        style={{
          position: 'relative',
          height: filtered.length * ROW_HEIGHT + 40,
          background: '#fafafa',
          padding: 16,
          overflowX: 'auto',
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 16,
            right: 16,
            fontSize: 11,
            color: '#8c8c8c',
          }}
        >
          <span>{minDate.format('YYYY-MM')}</span>
          <span style={{ float: 'right' }}>{maxDate.format('YYYY-MM')}</span>
        </div>

        {filtered.map((e, i) => {
          const startDays = dayjs(e.valid_from).diff(minDate, 'day')
          const endDays = (e.valid_to ? dayjs(e.valid_to) : maxDate).diff(
            minDate,
            'day',
          )
          const leftPct = (startDays / totalDays) * 100
          const widthPct = ((endDays - startDays) / totalDays) * 100
          const status = classifyEdgeStatus({
            ...e,
            // GraphEdgeLike compat (rel + bi-temporal fields, source/target node id placeholders)
            source_node_id: '',
            target_node_id: '',
          })
          const barTitle = `${e.source_label} → ${e.target_label}`
          return (
            <Tooltip
              key={e.edge_id}
              title={
                <div>
                  <div>
                    {REL_TYPE_LABELS[e.rel_type] ?? e.rel_type}: {barTitle}
                  </div>
                  <div>
                    {e.valid_from} → {e.valid_to ?? '(进行中)'}
                  </div>
                  <div>importance: {e.importance}</div>
                </div>
              }
            >
              <div
                data-testid={`timeline-bar-${e.edge_id}`}
                style={{
                  position: 'absolute',
                  top: i * ROW_HEIGHT + 24,
                  left: `${leftPct}%`,
                  width: `${Math.max(widthPct, 0.5)}%`,
                  height: BAR_HEIGHT,
                  background: REL_COLORS[e.rel_type] ?? '#bfbfbf',
                  opacity:
                    status === 'invalidated'
                      ? 0.3
                      : status === 'ended'
                        ? 0.7
                        : 1,
                  borderRadius: 4,
                  fontSize: 10,
                  color: '#fff',
                  padding: '2px 6px',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  cursor: 'pointer',
                }}
              >
                {barTitle}
              </div>
            </Tooltip>
          )
        })}
      </div>

      <div style={{ marginTop: 16, fontSize: 12, color: '#8c8c8c' }}>
        {Object.entries(REL_TYPE_LABELS).map(([k, v]) => (
          <Tag key={k} color={REL_COLORS[k] ?? 'default'}>
            {v}
          </Tag>
        ))}
      </div>
    </div>
  )
}
