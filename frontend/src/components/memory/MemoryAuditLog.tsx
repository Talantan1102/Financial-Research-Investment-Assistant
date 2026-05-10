/**
 * MemoryAuditLog (Plan 7B Task 4) — invalidated edges 历史 + 一键否决.
 *
 * 默认展示 invalidated_at IS NOT NULL 的纠错 audit (按 invalidated_at DESC).
 * Switch 切到 "active" 模式: 展示当前 valid_to IS NULL && invalidated_at IS NULL
 * 的 active edge, 每行可一键否决 (POST /memory/edges/{id}/invalidate).
 *
 * spec § 9 视图 3 + § 11 末尾 #8 用户回路 first-class hook (一键否决).
 */
import { Button, Empty, Popconfirm, Spin, Switch, Table, Tag, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useState } from 'react'
import {
  fetchMemoryAudit,
  fetchMemoryGraph,
  invalidateMemoryEdge,
} from '@/api/memoryApi'
import type { AuditEdge, MemoryEdge, MemoryNode } from '@/types/memory'
import { REL_TYPE_LABELS } from './MemoryGraph.styles'

/**
 * Unified row shape for the table — covers both audit (invalidated) and
 * active rows. invalidated_at is always present for audit rows; null for
 * active rows. source_label / target_label always present.
 */
interface Row {
  edge_id: string
  rel_type: string
  source_label: string
  target_label: string
  valid_from?: string | null
  valid_to?: string | null
  invalidated_at: string | null
  reasoning: string | null
  status: 'current' | 'ended' | 'invalidated'
}

function auditToRow(a: AuditEdge): Row {
  return {
    edge_id: a.edge_id,
    rel_type: a.rel_type,
    source_label: a.source_label,
    target_label: a.target_label,
    valid_from: null,
    valid_to: null,
    invalidated_at: a.invalidated_at,
    reasoning: a.original_reasoning,
    status: 'invalidated',
  }
}

function activeEdgeToRow(
  e: MemoryEdge,
  nodeMap: Map<string, MemoryNode>,
): Row {
  const src = nodeMap.get(e.source_node_id)
  const tgt = nodeMap.get(e.target_node_id)
  return {
    edge_id: e.edge_id,
    rel_type: e.rel_type,
    source_label: src?.entity_label ?? e.source_node_id,
    target_label: tgt?.entity_label ?? e.target_node_id,
    valid_from: e.valid_from,
    valid_to: e.valid_to,
    invalidated_at: null,
    reasoning: e.reasoning,
    status: e.valid_to ? 'ended' : 'current',
  }
}

export default function MemoryAuditLog() {
  const [rows, setRows] = useState<Row[]>([])
  const [loading, setLoading] = useState(true)
  const [showActive, setShowActive] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    if (showActive) {
      fetchMemoryGraph()
        .then((data) => {
          if (cancelled) return
          const nodeMap = new Map<string, MemoryNode>(
            data.nodes.map((n) => [n.node_id, n]),
          )
          const activeRows = data.edges
            .map((e) => activeEdgeToRow(e, nodeMap))
            .filter((r) => r.status !== 'invalidated')
          setRows(activeRows)
        })
        .catch(() => {
          if (!cancelled) setRows([])
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    } else {
      fetchMemoryAudit()
        .then((data) => {
          if (cancelled) return
          setRows(data.items.map(auditToRow))
        })
        .catch(() => {
          if (!cancelled) setRows([])
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    }
    return () => {
      cancelled = true
    }
  }, [showActive, reloadKey])

  const handleInvalidate = async (edgeId: string) => {
    try {
      await invalidateMemoryEdge(edgeId)
      message.success('已否决, 该 edge 不会再影响后续 retrieval')
      setReloadKey((k) => k + 1)
    } catch (e) {
      message.error(`否决失败: ${String((e as Error)?.message ?? e)}`)
    }
  }

  const columns: ColumnsType<Row> = [
    {
      title: '状态',
      key: 'status',
      width: 100,
      render: (_v, row) => (
        <Tag
          color={
            row.status === 'current'
              ? 'green'
              : row.status === 'ended'
                ? 'orange'
                : 'default'
          }
        >
          {row.status}
        </Tag>
      ),
    },
    {
      title: 'Fact',
      key: 'fact',
      render: (_v, row) => (
        <span>
          {row.source_label}{' '}
          <Tag>{REL_TYPE_LABELS[row.rel_type] ?? row.rel_type}</Tag>{' '}
          {row.target_label}
        </span>
      ),
    },
    {
      title: 'valid_from',
      dataIndex: 'valid_from',
      width: 130,
      render: (v: string | null) => v ?? '—',
    },
    {
      title: 'valid_to',
      dataIndex: 'valid_to',
      width: 130,
      render: (v: string | null) => v ?? '—',
    },
    {
      title: 'invalidated_at',
      dataIndex: 'invalidated_at',
      width: 150,
      render: (v: string | null) => v ?? '—',
    },
    { title: 'reasoning', dataIndex: 'reasoning', ellipsis: true },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_v, row) => {
        if (row.status !== 'current') {
          return <span style={{ color: '#bfbfbf' }}>—</span>
        }
        return (
          <Popconfirm
            title="确认否决这条 fact?"
            description="否决后该 edge 不再参与未来 retrieval (可在 audit 看到记录)"
            onConfirm={() => handleInvalidate(row.edge_id)}
            okText="否决"
            cancelText="取消"
          >
            <Button
              danger
              size="small"
              data-testid={`invalidate-btn-${row.edge_id}`}
            >
              一键否决
            </Button>
          </Popconfirm>
        )
      },
    },
  ]

  if (loading)
    return (
      <div data-testid="memory-audit-loading" style={{ padding: 24 }}>
        <Spin size="large" />
      </div>
    )

  if (rows.length === 0)
    return (
      <div data-testid="memory-audit">
        <ToggleBar showActive={showActive} setShowActive={setShowActive} />
        <Empty
          description={
            showActive
              ? '没有 active edge'
              : '暂无被纠正的记录 (说明 memory 工作得不错)'
          }
        />
      </div>
    )

  return (
    <div data-testid="memory-audit">
      <ToggleBar showActive={showActive} setShowActive={setShowActive} />
      <Table
        rowKey="edge_id"
        columns={columns}
        dataSource={rows}
        pagination={{ pageSize: 20 }}
        size="small"
      />
    </div>
  )
}

interface ToggleBarProps {
  showActive: boolean
  setShowActive: (v: boolean) => void
}

function ToggleBar({ showActive, setShowActive }: ToggleBarProps) {
  return (
    <div
      style={{
        marginBottom: 16,
        display: 'flex',
        gap: 12,
        alignItems: 'center',
      }}
    >
      <Switch
        checked={showActive}
        onChange={setShowActive}
        data-testid="toggle-active"
      />
      <span>
        {showActive
          ? '显示 active edge (可一键否决)'
          : '显示 invalidated 历史 (audit log)'}
      </span>
    </div>
  )
}
