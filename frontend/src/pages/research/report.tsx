/**
 * frontend/src/pages/research/report.tsx
 * D output report page — fetches GET /api/v0.5/research/:id and renders
 * the full InvestmentDueDiligenceReport.
 *
 * Layout:
 *   - Disclaimer (top)
 *   - TL;DR summary strip
 *   - 3-column grid: [sticky outline | report content | collapsible evidence]
 *   - Disclaimer (bottom)
 *   - Actions: copy markdown + print PDF
 *
 * Path A decision (Task 6): SSE streaming lives in new.tsx; report.tsx is
 * purely a GET + render page navigated to after done event.
 */

import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Button,
  Card,
  Col,
  Row,
  Skeleton,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  ArrowLeftOutlined,
  CopyOutlined,
  PrinterOutlined,
} from '@ant-design/icons'
import { getResearchReport } from '@/api/research'
import Markdown from '@/components/markdown'
import type {
  ErrorState,
  InvestmentDueDiligenceReport,
  OverallRiskLevel,
  Recommendation,
  RiskItem,
} from '@/types/research'
import {
  RECOMMENDATION_LABELS,
  RISK_LEVEL_LABELS,
} from '@/types/research'
import Disclaimer from './components/Disclaimer'
import ErrorBanner from './components/ErrorBanner'
import EvidenceSidebar from './components/EvidenceSidebar'
import ReportOutline from './components/ReportOutline'
import { SECTION_ANCHORS } from './components/sectionAnchors'

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
  accentGreen: '#27875a',
  accentYellow: '#b8860b',
  accentRed: '#c0392b',
  monoFont: '"SF Mono", "JetBrains Mono", Consolas, monospace',
}

// ── Recommendation colors ─────────────────────────────────────────────────────
const RECOMMENDATION_COLOR: Record<string, string> = {
  recommend_buy: 'green',
  recommend_overweight: 'blue',
  recommend_hold: 'default',
  recommend_underweight: 'orange',
  recommend_sell: 'red',
}

const RISK_LEVEL_COLOR: Record<OverallRiskLevel, string> = {
  low: 'green',
  medium: 'blue',
  high: 'orange',
  very_high: 'red',
}

// ── Utility: format money ─────────────────────────────────────────────────────
function fmtCny(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1e8) return `¥${(n / 1e8).toFixed(2)}亿`
  if (n >= 1e4) return `¥${(n / 1e4).toFixed(0)}万`
  return `¥${n.toFixed(2)}`
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return '—'
  return `${(n * 100).toFixed(2)}%`
}

function fmtNum(n: number | null | undefined, decimals = 2): string {
  if (n == null) return '—'
  return n.toFixed(decimals)
}

function fmtDatetime(iso: string): string {
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

// ── Section card wrapper ──────────────────────────────────────────────────────
interface SectionCardProps {
  id: string
  title: string
  children: React.ReactNode
}

function SectionCard({ id, title, children }: SectionCardProps) {
  return (
    <div
      id={id}
      style={{
        marginBottom: 24,
        scrollMarginTop: 16,
      }}
    >
      <Card
        style={{
          borderColor: TOKEN.borderColor,
          borderRadius: 10,
        }}
        styles={{ body: { padding: '24px 28px' } }}
      >
        <Title
          level={4}
          style={{
            margin: '0 0 16px',
            fontSize: 16,
            fontWeight: 600,
            color: TOKEN.textPrimary,
            borderBottom: `2px solid ${TOKEN.accentBlue}`,
            paddingBottom: 8,
          }}
        >
          {title}
        </Title>
        {children}
      </Card>
    </div>
  )
}

// ── Key-value row ─────────────────────────────────────────────────────────────
function KVRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        gap: 12,
        padding: '6px 0',
        borderBottom: `1px solid ${TOKEN.borderColor}`,
        alignItems: 'baseline',
      }}
    >
      <span style={{ width: 120, flexShrink: 0, fontSize: 12, color: TOKEN.textTertiary }}>
        {label}
      </span>
      <span style={{ fontSize: 13, color: TOKEN.textPrimary, flex: 1 }}>{value}</span>
    </div>
  )
}

// ── § 1 Target Overview ───────────────────────────────────────────────────────
function Section1({ data }: { data: InvestmentDueDiligenceReport['target_overview'] }) {
  return (
    <SectionCard id={SECTION_ANCHORS[0].id} title={SECTION_ANCHORS[0].label}>
      <Markdown value={data.narrative} />
      <div style={{ marginTop: 16 }}>
        <KVRow label="主营业务" value={data.main_business} />
        {data.registered_capital && (
          <KVRow label="注册资本" value={data.registered_capital} />
        )}
        {data.controlling_shareholder && (
          <KVRow label="控股股东" value={data.controlling_shareholder} />
        )}
        {data.listing_status && (
          <KVRow label="上市状态" value={data.listing_status} />
        )}
        {data.current_pe != null && (
          <KVRow label="市盈率 (PE)" value={`${data.current_pe.toFixed(2)}x`} />
        )}
        {data.current_pb != null && (
          <KVRow label="市净率 (PB)" value={`${data.current_pb.toFixed(2)}x`} />
        )}
        {data.current_market_cap != null && (
          <KVRow label="市值" value={fmtCny(data.current_market_cap)} />
        )}
        {data.dividend_yield != null && (
          <KVRow label="股息率" value={fmtPct(data.dividend_yield)} />
        )}
      </div>
    </SectionCard>
  )
}

// ── § 2 Legal Qualification ───────────────────────────────────────────────────
function Section2({ data }: { data: InvestmentDueDiligenceReport['legal_qualification'] }) {
  return (
    <SectionCard id={SECTION_ANCHORS[1].id} title={SECTION_ANCHORS[1].label}>
      <Markdown value={data.narrative} />
      <div style={{ marginTop: 16 }}>
        <KVRow label="法律状态" value={data.legal_status} />
        {data.business_qualifications.length > 0 && (
          <KVRow
            label="业务资质"
            value={
              <ul style={{ margin: 0, paddingLeft: 16 }}>
                {data.business_qualifications.map((q, i) => (
                  <li key={i} style={{ fontSize: 13 }}>{q}</li>
                ))}
              </ul>
            }
          />
        )}
        {data.adverse_records.length > 0 && (
          <KVRow
            label="不良记录"
            value={
              <ul style={{ margin: 0, paddingLeft: 16 }}>
                {data.adverse_records.map((r, i) => (
                  <li key={i} style={{ fontSize: 13, color: TOKEN.accentRed }}>{r}</li>
                ))}
              </ul>
            }
          />
        )}
      </div>
    </SectionCard>
  )
}

// ── § 3 Financial Analysis ────────────────────────────────────────────────────
function Section3({ data }: { data: InvestmentDueDiligenceReport['financial_analysis'] }) {
  return (
    <SectionCard id={SECTION_ANCHORS[2].id} title={SECTION_ANCHORS[2].label}>
      <Markdown value={data.narrative} />
      {data.key_metrics.length > 0 && (
        <div
          style={{
            marginTop: 16,
            overflowX: 'auto',
          }}
        >
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: 12,
            }}
          >
            <thead>
              <tr style={{ backgroundColor: '#f5f2ec' }}>
                <th style={{ padding: '8px 10px', textAlign: 'left', color: TOKEN.textSecondary, borderBottom: `1px solid ${TOKEN.borderColor}` }}>指标</th>
                <th style={{ padding: '8px 10px', textAlign: 'right', color: TOKEN.textSecondary, borderBottom: `1px solid ${TOKEN.borderColor}` }}>数值</th>
                <th style={{ padding: '8px 10px', textAlign: 'right', color: TOKEN.textSecondary, borderBottom: `1px solid ${TOKEN.borderColor}` }}>期间</th>
                <th style={{ padding: '8px 10px', textAlign: 'right', color: TOKEN.textSecondary, borderBottom: `1px solid ${TOKEN.borderColor}` }}>同比</th>
              </tr>
            </thead>
            <tbody>
              {data.key_metrics.map((m, i) => (
                <tr
                  key={i}
                  style={{ borderBottom: `1px solid ${TOKEN.borderColor}` }}
                >
                  <td style={{ padding: '7px 10px', color: TOKEN.textPrimary }}>{m.name}</td>
                  <td style={{ padding: '7px 10px', textAlign: 'right', fontFamily: TOKEN.monoFont }}>{m.value}</td>
                  <td style={{ padding: '7px 10px', textAlign: 'right', color: TOKEN.textTertiary }}>{m.period}</td>
                  <td
                    style={{
                      padding: '7px 10px',
                      textAlign: 'right',
                      fontFamily: TOKEN.monoFont,
                      color:
                        m.yoy_change?.startsWith('-')
                          ? TOKEN.accentRed
                          : m.yoy_change
                            ? TOKEN.accentGreen
                            : TOKEN.textTertiary,
                    }}
                  >
                    {m.yoy_change ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div style={{ marginTop: 16 }}>
        <div style={{ marginBottom: 12 }}>
          <strong style={{ fontSize: 13, color: TOKEN.textSecondary }}>盈利能力</strong>
          <Markdown value={data.profitability_analysis} />
        </div>
        <div style={{ marginBottom: 12 }}>
          <strong style={{ fontSize: 13, color: TOKEN.textSecondary }}>成长性</strong>
          <Markdown value={data.growth_analysis} />
        </div>
        <div style={{ marginBottom: 12 }}>
          <strong style={{ fontSize: 13, color: TOKEN.textSecondary }}>回报分析</strong>
          <Markdown value={data.return_analysis} />
        </div>
        <div style={{ marginBottom: 12 }}>
          <strong style={{ fontSize: 13, color: TOKEN.textSecondary }}>现金流</strong>
          <Markdown value={data.cash_flow_analysis} />
        </div>
        {data.valuation_analysis && (
          <div>
            <strong style={{ fontSize: 13, color: TOKEN.textSecondary }}>估值分析</strong>
            <Markdown value={data.valuation_analysis.narrative} />
            {data.valuation_analysis.pe_historical_percentile && (
              <KVRow label="PE 历史分位" value={data.valuation_analysis.pe_historical_percentile} />
            )}
            {data.valuation_analysis.dcf_valuation && (
              <KVRow label="DCF 估值" value={data.valuation_analysis.dcf_valuation} />
            )}
            {data.valuation_analysis.peer_comparison && (
              <KVRow label="可比公司" value={data.valuation_analysis.peer_comparison} />
            )}
          </div>
        )}
      </div>
    </SectionCard>
  )
}

// ── § 4 Industry Analysis ─────────────────────────────────────────────────────
function Section4({ data }: { data: InvestmentDueDiligenceReport['industry_analysis'] }) {
  return (
    <SectionCard id={SECTION_ANCHORS[3].id} title={SECTION_ANCHORS[3].label}>
      <Markdown value={data.narrative} />
      <div style={{ marginTop: 16 }}>
        <KVRow label="所属行业" value={data.industry_name} />
        <KVRow label="行业展望" value={<Markdown value={data.industry_outlook} />} />
        <KVRow label="竞争地位" value={<Markdown value={data.competitive_position} />} />
        {data.key_competitors.length > 0 && (
          <KVRow
            label="主要竞争对手"
            value={
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {data.key_competitors.map((c, i) => (
                  <Tag key={i} style={{ fontSize: 12, borderColor: TOKEN.borderColor }}>{c}</Tag>
                ))}
              </div>
            }
          />
        )}
        <KVRow label="政策影响" value={<Markdown value={data.policy_impact} />} />
      </div>
    </SectionCard>
  )
}

// ── Risk item card ────────────────────────────────────────────────────────────
function RiskItemCard({ item }: { item: RiskItem }) {
  const severityColor =
    item.severity === 'high'
      ? TOKEN.accentRed
      : item.severity === 'medium'
        ? TOKEN.accentYellow
        : TOKEN.accentGreen

  return (
    <div
      style={{
        border: `1px solid ${TOKEN.borderColor}`,
        borderLeft: `3px solid ${severityColor}`,
        borderRadius: 6,
        padding: '10px 14px',
        marginBottom: 10,
        backgroundColor: '#fefefe',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <strong style={{ fontSize: 13, color: TOKEN.textPrimary }}>{item.title}</strong>
        <Tag
          color={item.severity === 'high' ? 'red' : item.severity === 'medium' ? 'orange' : 'green'}
          style={{ fontSize: 11 }}
        >
          {item.severity === 'high' ? '高' : item.severity === 'medium' ? '中' : '低'}
        </Tag>
      </div>
      <p style={{ fontSize: 12, color: TOKEN.textSecondary, margin: '0 0 6px' }}>
        {item.description}
      </p>
      {item.mitigations.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12, color: TOKEN.textTertiary }}>
          {item.mitigations.map((m, i) => (
            <li key={i}>{m}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── § 5 Risk Assessment ───────────────────────────────────────────────────────
const RISK_CATEGORIES: { key: keyof Pick<InvestmentDueDiligenceReport['risk_assessment'], 'market_risk' | 'growth_risk' | 'event_risk' | 'valuation_risk'>; label: string }[] = [
  { key: 'market_risk', label: '市场风险' },
  { key: 'growth_risk', label: '成长风险' },
  { key: 'event_risk', label: '事件风险' },
  { key: 'valuation_risk', label: '估值风险' },
]

function Section5({ data }: { data: InvestmentDueDiligenceReport['risk_assessment'] }) {
  return (
    <SectionCard id={SECTION_ANCHORS[4].id} title={SECTION_ANCHORS[4].label}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <span style={{ fontSize: 13, color: TOKEN.textSecondary }}>综合风险等级</span>
        <Tag
          color={RISK_LEVEL_COLOR[data.overall_risk_level]}
          style={{ fontSize: 13, padding: '2px 10px' }}
        >
          {RISK_LEVEL_LABELS[data.overall_risk_level]}
        </Tag>
      </div>
      <Markdown value={data.narrative} />
      <div style={{ marginTop: 16 }}>
        {RISK_CATEGORIES.map(({ key, label }) => {
          const items = data[key] as RiskItem[]
          if (!items || items.length === 0) return null
          return (
            <div key={key} style={{ marginBottom: 16 }}>
              <h4 style={{ marginTop: 16, marginBottom: 8, fontSize: 14, color: TOKEN.textSecondary, fontWeight: 600 }}>
                {label}
              </h4>
              {items.map((item, i) => (
                <RiskItemCard key={i} item={item} />
              ))}
            </div>
          )
        })}
      </div>
    </SectionCard>
  )
}

// ── § 6 Investment Recommendation ────────────────────────────────────────────
function Section6({ data, report }: { data: InvestmentDueDiligenceReport['investment_recommendation']; report: InvestmentDueDiligenceReport }) {
  const recLabel = RECOMMENDATION_LABELS[data.recommendation as Recommendation] ?? data.recommendation
  const recColor = RECOMMENDATION_COLOR[data.recommendation] ?? 'default'

  return (
    <SectionCard id={SECTION_ANCHORS[5].id} title={SECTION_ANCHORS[5].label}>
      {/* Hero recommendation */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          padding: '16px 20px',
          backgroundColor: '#f5f7ff',
          borderRadius: 8,
          marginBottom: 20,
          border: `1px solid ${TOKEN.borderColor}`,
        }}
      >
        <Tag
          color={recColor}
          style={{ fontSize: 18, padding: '6px 16px', fontWeight: 700 }}
        >
          {recLabel}
        </Tag>
        <div>
          <div style={{ fontSize: 13, color: TOKEN.textSecondary }}>
            建议仓位：
            <strong style={{ color: TOKEN.textPrimary }}>
              {data.recommended_position_size_pct.toFixed(1)}%
            </strong>
          </div>
        </div>
      </div>

      <Markdown value={data.narrative} />

      <div style={{ marginTop: 16 }}>
        <KVRow
          label="建议买入区间"
          value={
            <span style={{ fontFamily: TOKEN.monoFont }}>
              ¥{fmtNum(data.recommended_entry_price_range.low)} — ¥{fmtNum(data.recommended_entry_price_range.high)}
            </span>
          }
        />
        <KVRow
          label="止损价"
          value={
            <span style={{ fontFamily: TOKEN.monoFont, color: TOKEN.accentRed }}>
              ¥{fmtNum(data.recommended_stop_loss_price)}
            </span>
          }
        />
        <KVRow
          label="目标价区间"
          value={
            <span style={{ fontFamily: TOKEN.monoFont, color: TOKEN.accentGreen }}>
              ¥{fmtNum(data.estimated_target_price_range.low)} — ¥{fmtNum(data.estimated_target_price_range.high)}
            </span>
          }
        />
        {report.target_close_price_at_gen != null && (
          <KVRow
            label="生成时收盘价"
            value={
              <span style={{ fontFamily: TOKEN.monoFont }}>
                ¥{fmtNum(report.target_close_price_at_gen)}
              </span>
            }
          />
        )}
        {report.target_market_cap_at_gen != null && (
          <KVRow label="生成时市值" value={fmtCny(report.target_market_cap_at_gen)} />
        )}
        {data.position_management_conditions.length > 0 && (
          <KVRow
            label="仓位管理条件"
            value={
              <ul style={{ margin: 0, paddingLeft: 16 }}>
                {data.position_management_conditions.map((c, i) => (
                  <li key={i} style={{ fontSize: 13 }}>{c}</li>
                ))}
              </ul>
            }
          />
        )}
      </div>
    </SectionCard>
  )
}

// ── TL;DR strip ───────────────────────────────────────────────────────────────
function TldrStrip({ report }: { report: InvestmentDueDiligenceReport }) {
  // Construct TL;DR from § 6 narrative first paragraph or § 1 narrative
  const tldr =
    report.investment_recommendation.narrative.split('\n')[0] ||
    report.target_overview.narrative.split('\n')[0] ||
    ''

  const recLabel = RECOMMENDATION_LABELS[report.investment_recommendation.recommendation as Recommendation]
  const recColor = RECOMMENDATION_COLOR[report.investment_recommendation.recommendation] ?? 'default'

  return (
    <div
      style={{
        backgroundColor: TOKEN.cardBg,
        border: `1px solid ${TOKEN.borderColor}`,
        borderRadius: 10,
        padding: '16px 24px',
        marginBottom: 20,
        display: 'flex',
        alignItems: 'flex-start',
        gap: 16,
      }}
    >
      <div style={{ flexShrink: 0 }}>
        <Tag color={recColor} style={{ fontSize: 13, padding: '3px 12px', fontWeight: 600 }}>
          {recLabel}
        </Tag>
        <div style={{ marginTop: 4, fontSize: 11, color: TOKEN.textTertiary, textAlign: 'center' }}>
          建议{(report.investment_recommendation.recommended_position_size_pct).toFixed(1)}%仓
        </div>
      </div>
      <div style={{ flex: 1 }}>
        <p style={{ margin: 0, fontSize: 14, color: TOKEN.textPrimary, lineHeight: 1.6 }}>
          {tldr}
        </p>
        <div style={{ marginTop: 6, fontSize: 11, color: TOKEN.textTertiary, fontFamily: TOKEN.monoFont }}>
          生成于 {fmtDatetime(report.generated_at)} · {report.target_name} ({report.target_ts_code})
        </div>
      </div>
    </div>
  )
}

// ── Build markdown export ─────────────────────────────────────────────────────
function buildMarkdownExport(report: InvestmentDueDiligenceReport): string {
  const rec = report.investment_recommendation
  const recLabel = RECOMMENDATION_LABELS[rec.recommendation as Recommendation] ?? rec.recommendation

  const lines: string[] = [
    `# ${report.target_name}（${report.target_ts_code}）投资尽调报告`,
    ``,
    `> 生成时间：${fmtDatetime(report.generated_at)}`,
    `> 建议评级：**${recLabel}**｜建议仓位：**${rec.recommended_position_size_pct.toFixed(1)}%**`,
    ``,
    `---`,
    ``,
    `## § 1 公司概况`,
    ``,
    report.target_overview.narrative,
    ``,
    `---`,
    ``,
    `## § 2 法律资质`,
    ``,
    report.legal_qualification.narrative,
    ``,
    `---`,
    ``,
    `## § 3 财务分析`,
    ``,
    report.financial_analysis.narrative,
    ``,
    `---`,
    ``,
    `## § 4 行业分析`,
    ``,
    report.industry_analysis.narrative,
    ``,
    `---`,
    ``,
    `## § 5 风险评估`,
    ``,
    `综合风险等级：**${RISK_LEVEL_LABELS[report.risk_assessment.overall_risk_level]}**`,
    ``,
    report.risk_assessment.narrative,
    ``,
    `---`,
    ``,
    `## § 6 投资建议`,
    ``,
    rec.narrative,
    ``,
    `- 建议买入区间：¥${fmtNum(rec.recommended_entry_price_range.low)} — ¥${fmtNum(rec.recommended_entry_price_range.high)}`,
    `- 止损价：¥${fmtNum(rec.recommended_stop_loss_price)}`,
    `- 目标价区间：¥${fmtNum(rec.estimated_target_price_range.low)} — ¥${fmtNum(rec.estimated_target_price_range.high)}`,
    ``,
    `---`,
    ``,
    `## 免责声明`,
    ``,
    report.disclaimer,
  ]

  return lines.join('\n')
}

// ── Loading skeleton ──────────────────────────────────────────────────────────
function LoadingSkeleton() {
  return (
    <div style={{ padding: '32px 24px', backgroundColor: TOKEN.pageBg, minHeight: '100%' }}>
      <Skeleton active paragraph={{ rows: 3 }} />
      <div style={{ marginTop: 24 }}>
        {[1, 2, 3].map((i) => (
          <Card key={i} style={{ marginBottom: 20, borderColor: TOKEN.borderColor, borderRadius: 10 }}>
            <Skeleton active paragraph={{ rows: 4 }} />
          </Card>
        ))}
      </div>
    </div>
  )
}

// ── Main page component ───────────────────────────────────────────────────────

export default function ResearchReport() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const [report, setReport] = useState<InvestmentDueDiligenceReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ErrorState | null>(null)
  const [evidenceCollapsed, setEvidenceCollapsed] = useState(false)
  const [copied, setCopied] = useState(false)

  const fetchReport = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const data = await getResearchReport(id)
      setReport(data)
    } catch (err: unknown) {
      setError({
        type: 'agent_crash',
        message: err instanceof Error ? err.message : '报告加载失败',
        requestId: id,
      })
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    void fetchReport()
  }, [fetchReport])

  const handleCopyMarkdown = useCallback(async () => {
    if (!report) return
    const md = buildMarkdownExport(report)
    try {
      await navigator.clipboard.writeText(md)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback for browsers without clipboard API
      const el = document.createElement('textarea')
      el.value = md
      document.body.appendChild(el)
      el.select()
      document.execCommand('copy')
      document.body.removeChild(el)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }, [report])

  if (loading) return <LoadingSkeleton />

  if (error && !report) {
    return (
      <div style={{ padding: '32px 24px', backgroundColor: TOKEN.pageBg, minHeight: '100%' }}>
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate('/research')}
          style={{ marginBottom: 16, borderColor: TOKEN.borderColor, color: TOKEN.textSecondary }}
        >
          返回列表
        </Button>
        <ErrorBanner
          error={error}
          onRetry={() => { void fetchReport() }}
          onDismiss={() => setError(null)}
        />
      </div>
    )
  }

  if (!report) return null

  // ── D output render ────────────────────────────────────────────────────────
  return (
    <div
      style={{
        padding: '24px 24px 48px',
        backgroundColor: TOKEN.pageBg,
        minHeight: '100%',
      }}
    >
      {/* Print CSS */}
      <style>{`
        @media print {
          .report-left-sticky,
          .report-right-sidebar,
          .report-actions,
          .report-back-btn {
            display: none !important;
          }
          .report-disclaimer-top,
          .report-disclaimer-bottom {
            display: block !important;
          }
        }
      `}</style>

      {/* ── Back button ── */}
      <div className="report-back-btn" style={{ marginBottom: 16 }}>
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate('/research')}
          style={{ borderColor: TOKEN.borderColor, color: TOKEN.textSecondary, fontSize: 13 }}
        >
          返回列表
        </Button>
      </div>

      {/* ── Page header ── */}
      <div style={{ marginBottom: 16 }}>
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
          {report.target_name}（{report.target_ts_code}）
        </Title>
        <Text style={{ fontSize: 13, color: TOKEN.textTertiary }}>
          投资尽调报告 · 生成于 {fmtDatetime(report.generated_at)}
        </Text>
      </div>

      {/* ── Degraded/error banner if present but report still loaded ── */}
      {error && (
        <div style={{ marginBottom: 16 }}>
          <ErrorBanner error={error} onDismiss={() => setError(null)} />
        </div>
      )}

      {/* ── Disclaimer top ── */}
      <div className="report-disclaimer-top">
        <Disclaimer report={report} position="top" />
      </div>

      {/* ── TL;DR strip ── */}
      <TldrStrip report={report} />

      {/* ── 3-column grid ── */}
      <Row gutter={[16, 0]} wrap={false} style={{ alignItems: 'flex-start' }}>
        {/* Left: sticky outline */}
        <Col
          flex="200px"
          className="report-left-sticky"
          style={{ flexShrink: 0 }}
        >
          <ReportOutline />
        </Col>

        {/* Center: report sections */}
        <Col flex="1" style={{ minWidth: 0 }}>
          <Section1 data={report.target_overview} />
          <Section2 data={report.legal_qualification} />
          <Section3 data={report.financial_analysis} />
          <Section4 data={report.industry_analysis} />
          <Section5 data={report.risk_assessment} />
          <Section6 data={report.investment_recommendation} report={report} />

          {/* ── Disclaimer bottom ── */}
          <div className="report-disclaimer-bottom">
            <Disclaimer report={report} position="bottom" />
          </div>

          {/* ── Actions ── */}
          <div
            className="report-actions"
            style={{
              marginTop: 24,
              display: 'flex',
              justifyContent: 'flex-end',
            }}
          >
            <Space>
              <Tooltip title={copied ? '已复制!' : '复制为 Markdown 格式'}>
                <Button
                  icon={<CopyOutlined />}
                  onClick={() => { void handleCopyMarkdown() }}
                  style={{ borderColor: TOKEN.borderColor, color: TOKEN.textSecondary }}
                >
                  {copied ? '已复制' : '复制 Markdown'}
                </Button>
              </Tooltip>
              <Button
                icon={<PrinterOutlined />}
                onClick={() => window.print()}
                style={{ borderColor: TOKEN.borderColor, color: TOKEN.textSecondary }}
              >
                打印 / PDF
              </Button>
            </Space>
          </div>
        </Col>

        {/* Right: collapsible evidence sidebar */}
        <Col
          flex={evidenceCollapsed ? '28px' : '220px'}
          className="report-right-sidebar"
          style={{ flexShrink: 0, transition: 'flex 0.2s' }}
        >
          <EvidenceSidebar
            report={report}
            collapsed={evidenceCollapsed}
            onToggle={() => setEvidenceCollapsed((v) => !v)}
          />
        </Col>
      </Row>
    </div>
  )
}
