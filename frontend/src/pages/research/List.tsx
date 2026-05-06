/**
 * frontend/src/pages/research/List.tsx
 *
 * v0.9.x research history list page (d 形态: antd Table + 时间分组 filter).
 * Reads from store/report.ts (Task 11) which wraps /reports CRUD endpoints.
 *
 * 列: 目标 / 投资建议 / 创建时间(默认降序) / 状态 / 成本 / 操作
 * 顶部 Radio.Group 时间分组 (今天 / 本周 / 本月 / 全部) — 前端纯 filter,
 * 不查后端;后端 list 已按 created_at desc 返回。
 */

import { useEffect, useState } from 'react'
import { Table, Button, Radio, Modal, Tag, Space } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { useSnapshot } from 'valtio'
import dayjs from 'dayjs'
import { reportState, reportActions } from '@/store/report'
import type { TimeFilter } from '@/store/report'
import type { ReportListItem, ReportStatus } from '@/api/reports'
import ResearchEntry from '@/components/research-entry'
import {
  RECOMMENDATION_LABELS,
  type Recommendation,
} from '@/types/research'
import styles from './List.module.scss'

// ── Status / recommendation visual mappings ──────────────────────────────────

const STATUS_COLOR: Record<ReportStatus, string> = {
  completed: 'green',
  streaming: 'blue',
  failed: 'red',
}

const STATUS_LABEL: Record<ReportStatus, string> = {
  completed: '完成',
  streaming: '进行中',
  failed: '失败',
}

const RECOMMENDATION_COLOR: Record<string, string> = {
  recommend_buy: 'green',
  recommend_overweight: 'blue',
  recommend_hold: 'default',
  recommend_underweight: 'orange',
  recommend_sell: 'red',
}

function formatRecommendation(rec: string | null): {
  label: string
  color: string
} | null {
  if (!rec) return null
  const label = RECOMMENDATION_LABELS[rec as Recommendation] ?? rec
  const color = RECOMMENDATION_COLOR[rec] ?? 'default'
  return { label, color }
}

// ── Page component ───────────────────────────────────────────────────────────

export default function ResearchListPage() {
  const navigate = useNavigate()
  const snap = useSnapshot(reportState)
  const [newModalOpen, setNewModalOpen] = useState(false)

  useEffect(() => {
    void reportActions.fetchList()
  }, [])

  // Time-group filter — pure client-side over the page already fetched.
  const filteredList = snap.list.filter((r) => {
    if (snap.timeFilter === 'all') return true
    const created = dayjs(r.created_at)
    const now = dayjs()
    if (snap.timeFilter === 'today') return created.isSame(now, 'day')
    if (snap.timeFilter === 'week')
      return created.isAfter(now.subtract(7, 'day'))
    if (snap.timeFilter === 'month')
      return created.isAfter(now.subtract(30, 'day'))
    return true
  })

  const handleDelete = (record: ReportListItem) => {
    Modal.confirm({
      title: '删除研报?',
      content: `「${record.target_name}」将被永久删除,无法恢复。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        await reportActions.deleteReport(record.id)
      },
    })
  }

  const columns: ColumnsType<ReportListItem> = [
    {
      title: '目标',
      dataIndex: 'target_name',
      key: 'target_name',
      sorter: (a, b) => a.target_name.localeCompare(b.target_name),
      render: (text: string, record) => (
        <a
          onClick={(e) => {
            e.stopPropagation()
            void navigate(`/research/${record.id}`)
          }}
        >
          {text}
        </a>
      ),
    },
    {
      title: '投资建议',
      dataIndex: 'investment_recommendation',
      key: 'investment_recommendation',
      filters: Object.entries(RECOMMENDATION_LABELS).map(([v, l]) => ({
        text: l,
        value: v,
      })),
      onFilter: (value, record) => record.investment_recommendation === value,
      render: (rec: string | null) => {
        const tag = formatRecommendation(rec)
        return tag ? <Tag color={tag.color}>{tag.label}</Tag> : '—'
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      sorter: (a, b) =>
        dayjs(a.created_at).valueOf() - dayjs(b.created_at).valueOf(),
      defaultSortOrder: 'descend',
      render: (t: string) => dayjs(t).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      filters: [
        { text: '完成', value: 'completed' },
        { text: '进行中', value: 'streaming' },
        { text: '失败', value: 'failed' },
      ],
      onFilter: (value, record) => record.status === value,
      render: (status: ReportStatus) => (
        <Tag color={STATUS_COLOR[status] ?? 'default'}>
          {STATUS_LABEL[status] ?? status}
        </Tag>
      ),
    },
    {
      title: '成本',
      dataIndex: 'cost',
      key: 'cost',
      sorter: (a, b) => a.cost - b.cost,
      render: (cost: number) => `¥${cost.toFixed(2)}`,
    },
    {
      title: '操作',
      key: 'action',
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            onClick={(e) => {
              e.stopPropagation()
              void navigate(`/research/${record.id}`)
            }}
          >
            查看
          </Button>
          <Button
            type="link"
            danger
            onClick={(e) => {
              e.stopPropagation()
              handleDelete(record)
            }}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>研究历史</h1>
        <Button type="primary" onClick={() => setNewModalOpen(true)}>
          新建研报
        </Button>
      </div>

      <Modal
        title="新建投资尽调研报"
        open={newModalOpen}
        onCancel={() => setNewModalOpen(false)}
        footer={null}
        destroyOnClose
        width={520}
      >
        <p style={{ color: '#6b7c93', marginBottom: 16 }}>
          5-agent 协作产出完整尽调报告 — 覆盖基本面、估值、风险与投资建议
        </p>
        <ResearchEntry
          onSuccess={(id) => {
            setNewModalOpen(false)
            void reportActions.fetchList()
            navigate(`/research/${id}`)
          }}
        />
      </Modal>
      <Radio.Group
        value={snap.timeFilter}
        onChange={(e) =>
          reportActions.setTimeFilter(e.target.value as TimeFilter)
        }
        className={styles.filter}
      >
        <Radio.Button value="today">今天</Radio.Button>
        <Radio.Button value="week">本周</Radio.Button>
        <Radio.Button value="month">本月</Radio.Button>
        <Radio.Button value="all">全部</Radio.Button>
      </Radio.Group>
      <Table<ReportListItem>
        rowKey="id"
        columns={columns}
        dataSource={filteredList as ReportListItem[]}
        loading={snap.listLoading}
        pagination={{ pageSize: 20, total: snap.listTotal }}
        onRow={(record) => ({
          style: { cursor: 'pointer' },
          onClick: () => navigate(`/research/${record.id}`),
        })}
      />
    </div>
  )
}
