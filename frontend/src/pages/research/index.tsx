/**
 * frontend/src/pages/research/index.tsx
 * 历史尽调列表页面。
 *
 * 列: 标的名称 (Link) / 股票代码 / 生成时间 / TL;DR 摘要 / 建议评级
 * 顶部 "新建尽调" 按钮 → /research/new
 */

import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  Button,
  Empty,
  Skeleton,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined, SyncOutlined } from '@ant-design/icons'
import { listResearchRuns } from '@/api/research'
import type { ResearchRunSummary } from '@/api/research'
import { RECOMMENDATION_LABELS } from '@/types/research'
import type { Recommendation } from '@/types/research'

const { Title, Text } = Typography

// ── Design tokens ─────────────────────────────────────────────────────────────
const TOKEN = {
  pageBg: '#faf9f7',
  cardBg: '#ffffff',
  borderColor: '#e8e4dc',
  textPrimary: '#1a1d21',
  textSecondary: '#5d6875',
  textTertiary: '#8a96a3',
  accentBlue: '#1d4ed8',
  monoFont: '"SF Mono", "JetBrains Mono", Consolas, monospace',
}

// ── Recommendation tag colours ────────────────────────────────────────────────
const RECOMMENDATION_COLOR: Record<string, string> = {
  recommend_buy: 'green',
  recommend_overweight: 'blue',
  recommend_hold: 'default',
  recommend_underweight: 'orange',
  recommend_sell: 'red',
}

function RecommendationTag({ value }: { value: string }) {
  const label =
    RECOMMENDATION_LABELS[value as Recommendation] ?? value
  const color = RECOMMENDATION_COLOR[value] ?? 'default'
  return <Tag color={color} style={{ fontSize: 12 }}>{label}</Tag>
}

// ── Format datetime ───────────────────────────────────────────────────────────
function formatTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ── Table columns ─────────────────────────────────────────────────────────────
const buildColumns = (): ColumnsType<ResearchRunSummary> => [
  {
    title: '标的',
    dataIndex: 'target_name',
    key: 'target_name',
    width: 160,
    render: (name: string, record: ResearchRunSummary) => (
      <Link
        to={`/research/${record.id}`}
        style={{
          color: TOKEN.textPrimary,
          fontWeight: 500,
        }}
      >
        {name || record.target_ts_code}
      </Link>
    ),
  },
  {
    title: '代码',
    dataIndex: 'target_ts_code',
    key: 'target_ts_code',
    width: 120,
    render: (code: string) => (
      <span
        style={{
          fontFamily: TOKEN.monoFont,
          fontSize: 12,
          color: TOKEN.textSecondary,
          letterSpacing: '0.04em',
        }}
      >
        {code}
      </span>
    ),
  },
  {
    title: '生成时间',
    dataIndex: 'generated_at',
    key: 'generated_at',
    width: 160,
    sorter: (a, b) =>
      new Date(a.generated_at).getTime() - new Date(b.generated_at).getTime(),
    defaultSortOrder: 'descend',
    render: (iso: string) => (
      <span
        style={{
          fontFamily: TOKEN.monoFont,
          fontSize: 12,
          color: TOKEN.textTertiary,
        }}
      >
        {formatTime(iso)}
      </span>
    ),
  },
  {
    title: 'TL;DR 摘要',
    dataIndex: 'tldr',
    key: 'tldr',
    ellipsis: true,
    render: (tldr: string) => (
      <span style={{ fontSize: 13, color: TOKEN.textSecondary }}>
        {tldr || '—'}
      </span>
    ),
  },
  {
    title: '建议',
    dataIndex: 'recommendation',
    key: 'recommendation',
    width: 100,
    filters: Object.entries(RECOMMENDATION_LABELS).map(([v, l]) => ({
      text: l,
      value: v,
    })),
    onFilter: (value, record) => record.recommendation === value,
    render: (rec: string) => <RecommendationTag value={rec} />,
  },
]

// ── Page component ────────────────────────────────────────────────────────────

export default function ResearchIndex() {
  const navigate = useNavigate()
  const [runs, setRuns] = useState<ResearchRunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const fetchRuns = useCallback(async (showLoader = true) => {
    if (showLoader) setLoading(true)
    else setRefreshing(true)
    try {
      const data = await listResearchRuns()
      // Sort descending by generated_at; backend also sorts but be defensive.
      const sorted = [...data].sort(
        (a, b) =>
          new Date(b.generated_at).getTime() -
          new Date(a.generated_at).getTime(),
      )
      setRuns(sorted)
    } catch (err) {
      console.error('[ResearchIndex] fetchRuns error:', err)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    void fetchRuns(true)
  }, [fetchRuns])

  const columns = buildColumns()

  return (
    <div
      style={{
        padding: 24,
        backgroundColor: TOKEN.pageBg,
        minHeight: '100%',
      }}
    >
      {/* ── Page header ── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 20,
        }}
      >
        <div>
          <Title
            level={3}
            style={{
              margin: 0,
              fontSize: 20,
              fontWeight: 600,
              color: TOKEN.textPrimary,
              letterSpacing: '-0.01em',
            }}
          >
            尽调记录
          </Title>
          <Text
            style={{
              fontSize: 13,
              color: TOKEN.textTertiary,
              marginTop: 4,
              display: 'block',
            }}
          >
            AI 投资标的尽调报告历史
          </Text>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Button
            icon={refreshing ? <SyncOutlined spin /> : <SyncOutlined />}
            onClick={() => {
              void fetchRuns(false)
            }}
            disabled={loading || refreshing}
            style={{ borderColor: TOKEN.borderColor, color: TOKEN.textSecondary }}
          >
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => navigate('/research/new')}
            style={{
              backgroundColor: TOKEN.accentBlue,
              borderColor: TOKEN.accentBlue,
              fontWeight: 500,
            }}
          >
            新建尽调
          </Button>
        </div>
      </div>

      {/* ── Table ── */}
      {loading && runs.length === 0 ? (
        <div
          style={{
            backgroundColor: TOKEN.cardBg,
            border: `1px solid ${TOKEN.borderColor}`,
            borderRadius: 8,
            padding: 24,
          }}
        >
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} active paragraph={{ rows: 1 }} />
          ))}
        </div>
      ) : (
        <div
          style={{
            backgroundColor: TOKEN.cardBg,
            border: `1px solid ${TOKEN.borderColor}`,
            borderRadius: 8,
            overflow: 'hidden',
          }}
        >
          <Table<ResearchRunSummary>
            rowKey="id"
            columns={columns}
            dataSource={runs}
            size="middle"
            pagination={{ pageSize: 20, showSizeChanger: false }}
            scroll={{ x: 800 }}
            loading={refreshing}
            locale={{
              emptyText: (
                <Empty
                  description={
                    <span style={{ color: TOKEN.textTertiary }}>
                      暂无尽调记录，点击右上角「新建尽调」开始
                    </span>
                  }
                />
              ),
            }}
            onRow={(record) => ({
              style: { transition: 'background 0.15s', cursor: 'pointer' },
              onMouseEnter: (e) => {
                ;(e.currentTarget as HTMLTableRowElement).style.backgroundColor =
                  'rgba(29,78,216,0.03)'
              },
              onMouseLeave: (e) => {
                ;(e.currentTarget as HTMLTableRowElement).style.backgroundColor =
                  ''
              },
              onClick: () => navigate(`/research/${record.id}`),
            })}
            style={{ fontSize: 13 }}
          />
        </div>
      )}
    </div>
  )
}
