import { useEffect, useState } from 'react'
import { Alert, Card, Col, Row, Spin, Statistic } from 'antd'
import Chart from '@/components/chart'
import { getOverview, type OverviewRead } from '@/api/portfolio'
import { pnlColor } from '@/utils/pnl-color'
import { structurePie } from './charts'

export default function PortfolioOverviewPage() {
  const [ov, setOv] = useState<OverviewRead | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    getOverview()
      .then((r) => setOv(r.data))
      .catch((e: unknown) => setErr(String(e)))
  }, [])

  if (err) {
    return (
      <Alert type="error" message="加载失败" description={err} showIcon />
    )
  }

  if (!ov) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }

  const s = ov.attribution.stock_breakdown

  return (
    <div style={{ padding: 24, maxWidth: 980, margin: '0 auto' }}>
      <h2>我的持仓 · 总览</h2>

      {/* 头条：总身家 + 今天 + 今年 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={24}>
          <Col>
            <Statistic title="总身家" value={ov.total_value} prefix="¥" />
          </Col>
          <Col>
            <Statistic
              title="今天"
              value={ov.today_pct}
              suffix="%"
              valueStyle={{ color: pnlColor(ov.today_pct) }}
            />
          </Col>
          <Col>
            <Statistic
              title="今年"
              value={ov.ytd_pct}
              suffix="%"
              valueStyle={{ color: pnlColor(ov.ytd_pct) }}
            />
          </Col>
        </Row>
        {ov.narrative && (
          <p
            style={{
              marginTop: 12,
              background: '#f2f2f7',
              borderRadius: 11,
              padding: '11px 13px',
            }}
          >
            {ov.narrative}
          </p>
        )}
      </Card>

      {/* 算账：stock_breakdown 三项 */}
      <Card title="这账怎么来的" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={8}>
            <Statistic
              title="跟着大盘"
              value={s.market}
              suffix="%"
              valueStyle={{ color: pnlColor(s.market) }}
            />
          </Col>
          <Col span={8}>
            <Statistic
              title="板块额外"
              value={s.sector_excess}
              suffix="%"
              valueStyle={{ color: pnlColor(s.sector_excess) }}
            />
          </Col>
          <Col span={8}>
            <Statistic
              title="个股自身"
              value={s.idiosyncratic}
              suffix="%"
              valueStyle={{ color: pnlColor(s.idiosyncratic) }}
            />
          </Col>
        </Row>
      </Card>

      {/* 看结构：饼图 + as_of 提示 */}
      <Card title="钱分在哪 · 按大类" style={{ marginBottom: 16 }}>
        <Chart config={structurePie(ov.structure.by_class)} />
        {ov.structure.as_of && (
          <p
            style={{
              fontSize: 12,
              color: '#8a6d1f',
              background: '#fff8e1',
              borderRadius: 9,
              padding: '8px 11px',
            }}
          >
            基金按最新季报(截至 {ov.structure.as_of})拆，之后可能已调仓。
          </p>
        )}
      </Card>
    </div>
  )
}
