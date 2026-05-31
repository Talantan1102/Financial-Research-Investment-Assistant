/**
 * frontend/src/pages/monitoring/index.tsx
 *
 * 持仓预警页 /monitoring — v1.0 signal-centric。
 *
 * 风格对齐: 与 reports / portfolio 一致,使用 antd 标准组件(Card/Table/Statistic/
 * Tag/Button/Input)+ 默认主题(白底 / SF Pro / antd 主题色),不再自造 token /
 * inline 样式(原「Perplexity/同花顺」米色+赭红+Mono 风格已移除)。
 *
 * 功能: 4 统计卡 + 搜索 + 立即扫描全部 + 信号表格 + 5s 轮询 + 详情链接 + fail-loud。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button,
  Card,
  Col,
  Empty,
  Input,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { SyncOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import {
  listSignals,
  triggerRefresh,
  type SignalSummary,
} from '@/api/monitoring'
import type { AlertLevel } from '@/types/monitoring'

const POLL_MS = 5000

// 预警等级 → antd Tag 标准语义色(success/warning/error),与全站主题一致
const LEVEL_TAG: Record<AlertLevel, { color: string; label: string }> = {
  green: { color: 'success', label: '正常' },
  yellow: { color: 'warning', label: '预警' },
  red: { color: 'error', label: '告警' },
}

function formatTime(iso: string | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function MonitoringIndex() {
  const [signals, setSignals] = useState<SignalSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [search, setSearch] = useState('')

  const refresh = useCallback(async () => {
    try {
      const s = await listSignals(50)
      setSignals(s)
    } catch (err) {
      console.error('[MonitoringIndex] refresh error:', err)
      void window.$app.message.error('加载监控信号失败，请检查登录状态或稍后重试')
    } finally {
      setLoading(false)
    }
  }, [])

  // 初始加载 + 5s 轮询
  useEffect(() => {
    void refresh()
    const timer = setInterval(() => {
      void refresh()
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [refresh])

  const stats = useMemo(() => {
    const since24h = Date.now() - 24 * 3600 * 1000
    const recent = signals.filter(
      (s) => s.created_at && new Date(s.created_at).getTime() > since24h,
    )
    const distinctTsCodes = new Set(signals.map((s) => s.ts_code))
    return {
      total: distinctTsCodes.size,
      todayScans: signals.length,
      yellow24h: recent.filter((s) => s.alert_level === 'yellow').length,
      red24h: recent.filter((s) => s.alert_level === 'red').length,
    }
  }, [signals])

  const filtered = useMemo(() => {
    return signals.filter(
      (s) =>
        !search ||
        s.ts_code.toLowerCase().includes(search.toLowerCase()) ||
        s.detail_status.toLowerCase().includes(search.toLowerCase()),
    )
  }, [signals, search])

  const handleScanAll = async () => {
    setScanning(true)
    try {
      const { status } = await triggerRefresh()
      void window.$app.message.success(`检测周期已入队 (${status})`)
      setTimeout(() => {
        void refresh()
      }, 1500)
    } catch (err) {
      console.error('[MonitoringIndex] triggerRefresh error:', err)
      void window.$app.message.error('触发扫描失败，请重试')
    } finally {
      setScanning(false)
    }
  }

  const columns: ColumnsType<SignalSummary> = [
    {
      title: '标的代码',
      dataIndex: 'ts_code',
      key: 'ts_code',
      width: 130,
      render: (code: string, record: SignalSummary) => (
        <Link to={`/monitoring/${record.id}/alert/${record.id}`}>{code}</Link>
      ),
    },
    {
      title: '预警等级',
      dataIndex: 'alert_level',
      key: 'alert_level',
      width: 100,
      render: (level: AlertLevel) => (
        <Tag color={LEVEL_TAG[level].color}>{LEVEL_TAG[level].label}</Tag>
      ),
    },
    {
      title: '详情状态',
      dataIndex: 'detail_status',
      key: 'detail_status',
      width: 120,
      render: (status: string) => <Tag>{status}</Tag>,
    },
    {
      title: '生成时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (ts: string | null) => formatTime(ts ?? undefined),
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_: unknown, record: SignalSummary) => (
        <Link to={`/monitoring/${record.id}/alert/${record.id}`}>详情</Link>
      ),
    },
  ]

  return (
    <div style={{ padding: 16 }}>
      {/* 统计卡 — antd Statistic,语义色仅在有预警/告警时高亮(antd warning/error) */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={12} lg={6}>
          <Card size="small">
            <Statistic title="监控标的数" value={stats.total} />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card size="small">
            <Statistic title="信号总数" value={stats.todayScans} />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card size="small">
            <Statistic
              title="黄色预警 (24h)"
              value={stats.yellow24h}
              valueStyle={stats.yellow24h > 0 ? { color: '#faad14' } : undefined}
            />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card size="small">
            <Statistic
              title="红色告警 (24h)"
              value={stats.red24h}
              valueStyle={stats.red24h > 0 ? { color: '#cf1322' } : undefined}
            />
          </Card>
        </Col>
      </Row>

      {/* 主卡片: 标题 + 搜索/扫描 + 信号表格 */}
      <Card
        title="持仓预警"
        extra={
          <Space>
            <Input.Search
              placeholder="搜索标的代码 / 详情状态"
              allowClear
              onChange={(e) => setSearch(e.target.value)}
              style={{ width: 220 }}
            />
            <Button
              type="primary"
              icon={scanning ? <SyncOutlined spin /> : <ThunderboltOutlined />}
              loading={scanning}
              onClick={() => {
                void handleScanAll()
              }}
            >
              立即扫描全部
            </Button>
          </Space>
        }
      >
        <div
          style={{ marginBottom: 12, fontSize: 13, color: 'rgba(0,0,0,0.45)' }}
        >
          每 5 秒自动刷新 · 监控客户持仓异动信号
        </div>
        <Table<SignalSummary>
          rowKey="id"
          columns={columns}
          dataSource={filtered}
          loading={loading && signals.length === 0}
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: false }}
          scroll={{ x: 600 }}
          locale={{
            emptyText: (
              <Empty
                description={
                  signals.length === 0
                    ? '暂无监控信号数据，点击「立即扫描全部」触发检测周期'
                    : '没有匹配的信号，请调整搜索条件'
                }
              />
            ),
          }}
        />
      </Card>
    </div>
  )
}
