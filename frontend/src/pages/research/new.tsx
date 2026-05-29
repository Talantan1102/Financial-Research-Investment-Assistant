/**
 * frontend/src/pages/research/new.tsx
 * B-1 新建尽调表单页面。
 *
 * 两态:
 *   1. form 态     — 6 字段表单
 *   2. progress 态 — submit 后展示研究日志 + 技术细节 expandable
 *                    直到 done 事件 → navigate /research/:id
 *
 * 6 字段:
 *   1. target_ts_code    — AutoComplete (ts_code + 名称联想)
 *   2. client_total_aum  — InputNumber  (CNY, 必填, > 0)
 *   3. client_existing_position — InputNumber (CNY, 可选, >= 0)
 *   4. investment_objective  — Select (4 选项)
 *   5. investment_horizon    — Select (3 选项)
 *   6. risk_tolerance        — Select (5 选项)
 *   user_message — TextArea (可选补充说明)
 *
 * Progress overlay 布局 (v0.8.4 业务化重构):
 *   主区: 业务化"研究日志" timeline (ProgressTimeline)
 *         — 自然语言 + emoji, 隐藏 agent 名
 *   技术细节 (collapsed by default): AgentStatusSidebar + 6-dim Critic 评分
 *         — 面试官 / 架构透明用
 *   底部 status bar: latency + cost
 *
 * SSE event 处理:
 *   plan          → 研究维度日志
 *   data_progress → 数据采集日志
 *   insight       → 关键洞察日志
 *   report_chunk  → 报告撰写完成 + streamingMd
 *   critic_score  → aggregate 时 emit 6-dim 评分
 *   done          → navigate /research/:id
 *   error         → ErrorBanner agent_crash
 */

import { useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AutoComplete,
  Button,
  Card,
  Form,
  InputNumber,
  Select,
  Typography,
  Input,
  Collapse,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import {
  autocompleteTsCode,
  submitResearch,
} from '@/api/research'
import {
  INVESTMENT_HORIZON_LABELS,
  INVESTMENT_OBJECTIVE_LABELS,
  RISK_TOLERANCE_LABELS,
} from '@/types/research'
import type {
  AgentName,
  AgentStateMap,
  CriticScores,
  ErrorState,
  InvestmentHorizon,
  InvestmentObjective,
  ResearchRequest,
  RiskTolerance,
  SSEResearchEvent,
  TsCodeSuggestion,
} from '@/types/research'
import AgentStatusSidebar from './components/AgentStatusSidebar'
import CostLatencyMetrics from './components/CostLatencyMetrics'
import ErrorBanner from './components/ErrorBanner'
import ProgressTimeline from './components/ProgressTimeline'
import type { TimelineEntry } from './components/ProgressTimeline'
import Markdown from '@/components/markdown'

const { Title, Text } = Typography
const { TextArea } = Input

// ── Design tokens (aligned with monitoring page) ──────────────────────────────
const TOKEN = {
  pageBg: '#faf9f7',
  cardBg: '#ffffff',
  borderColor: '#e8e4dc',
  textPrimary: '#1a1d21',
  textSecondary: '#5d6875',
  textTertiary: '#8a96a3',
  accentBlue: '#1d4ed8',
}

// ── Select options (built from i18n labels) ───────────────────────────────────

const OBJECTIVE_OPTIONS = (
  Object.entries(INVESTMENT_OBJECTIVE_LABELS) as [InvestmentObjective, string][]
).map(([value, label]) => ({ value, label }))

const HORIZON_OPTIONS = (
  Object.entries(INVESTMENT_HORIZON_LABELS) as [InvestmentHorizon, string][]
).map(([value, label]) => ({ value, label }))

const TOLERANCE_OPTIONS = (
  Object.entries(RISK_TOLERANCE_LABELS) as [RiskTolerance, string][]
).map(([value, label]) => ({ value, label }))

// ── Form field values type ────────────────────────────────────────────────────
interface FormValues {
  target_ts_code: string
  client_total_aum: number
  client_existing_position?: number
  investment_objective: InvestmentObjective
  investment_horizon: InvestmentHorizon
  risk_tolerance: RiskTolerance
  user_message?: string
}

// ── SSE event → agent state transitions ──────────────────────────────────────

function applySSEToAgentStates(
  prev: AgentStateMap,
  ev: SSEResearchEvent,
): AgentStateMap {
  const next = { ...prev }

  switch (ev.type) {
    case 'plan':
      // Planner running → done
      next['Planner'] = { name: 'Planner', status: 'done' }
      next['DataCollector'] = { name: 'DataCollector', status: 'running' }
      break

    case 'data_progress': {
      // DataCollector done — all tools completed (backend emits one event per node completion)
      // tools: human-readable labels; tool_names_raw: internal names
      const toolLabels = (ev.data['tools'] as string[] | undefined) ?? []
      const subtasks = toolLabels.map((label) => ({ label, status: 'done' as const }))
      next['DataCollector'] = {
        name: 'DataCollector',
        status: 'done',
        subtasks,
      }
      next['Analyst'] = { name: 'Analyst', status: 'running' }
      break
    }

    case 'insight':
      // Analyst done — insights generated
      // (DataCollector was already marked done via data_progress event)
      next['Analyst'] = { name: 'Analyst', status: 'done' }
      next['Writer'] = { name: 'Writer', status: 'running' }
      break

    case 'report_chunk':
      // Writer done — report generated
      next['Writer'] = { name: 'Writer', status: 'done' }
      next['Critic'] = { name: 'Critic', status: 'running' }
      break

    case 'critic_score': {
      // Individual scorer: Critic still running; aggregate: Critic done
      const scorer = (ev.data['scorer'] as string | undefined) ?? ''
      if (scorer === 'aggregate') {
        next['Critic'] = { name: 'Critic', status: 'done' }
      } else {
        // Keep Critic running during individual scorer execution
        if (next['Critic']?.status !== 'done') {
          next['Critic'] = { name: 'Critic', status: 'running' }
        }
      }
      break
    }

    case 'done':
      // All done
      for (const name of ['Planner', 'DataCollector', 'Analyst', 'Writer', 'Critic'] as AgentName[]) {
        if (next[name]?.status !== 'done') {
          next[name] = { name, status: 'done' }
        }
      }
      break

    case 'error': {
      const failedAgent = (ev.data['agent'] as AgentName | undefined)
      if (failedAgent) {
        next[failedAgent] = { name: failedAgent, status: 'failed' }
      }
      break
    }

    default:
      break
  }

  return next
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function ResearchNew() {
  const navigate = useNavigate()
  const [form] = Form.useForm<FormValues>()

  // ── Form state ──────────────────────────────────────────────────────────────
  const [submitting, setSubmitting] = useState(false)
  const [suggestions, setSuggestions] = useState<TsCodeSuggestion[]>([])
  const abortRef = useRef<(() => void) | null>(null)
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── C2 progress state ───────────────────────────────────────────────────────
  const [inProgress, setInProgress] = useState(false)
  const [agentStates, setAgentStates] = useState<AgentStateMap>({})
  const [costCny, setCostCny] = useState(0)
  const [latencyMs, setLatencyMs] = useState(0)
  const [criticScores, setCriticScores] = useState<CriticScores | null>(null)
  const [progressError, setProgressError] = useState<ErrorState | null>(null)
  // Streaming markdown: accumulated from report_chunk SSE events (spec § 4.3)
  const [streamingMd, setStreamingMd] = useState('')
  // Progress timeline entries for UX timeline display
  const [timelineEntries, setTimelineEntries] = useState<TimelineEntry[]>([])
  const startTimeRef = useRef<number>(0)
  const latencyTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── AutoComplete: fetch suggestions on input change (250ms debounce) ─────────
  const handleTsCodeSearch = useCallback((value: string) => {
    if (searchTimerRef.current !== null) {
      clearTimeout(searchTimerRef.current)
    }
    if (!value || value.length < 1) {
      setSuggestions([])
      return
    }
    searchTimerRef.current = setTimeout(() => {
      void autocompleteTsCode(value).then(setSuggestions).catch(() => {
        setSuggestions([])
      })
    }, 250)
  }, [])

  const autoCompleteOptions = suggestions.map((s) => ({
    value: s.ts_code,
    label: `${s.name}（${s.ts_code}）`,
  }))

  // ── Start latency ticker ──────────────────────────────────────────────────
  const startLatencyTicker = useCallback(() => {
    startTimeRef.current = Date.now()
    if (latencyTimerRef.current !== null) clearInterval(latencyTimerRef.current)
    latencyTimerRef.current = setInterval(() => {
      setLatencyMs(Date.now() - startTimeRef.current)
    }, 500)
  }, [])

  const stopLatencyTicker = useCallback(() => {
    if (latencyTimerRef.current !== null) {
      clearInterval(latencyTimerRef.current)
      latencyTimerRef.current = null
    }
    // One final accurate reading
    setLatencyMs(Date.now() - startTimeRef.current)
  }, [])

  // ── Retry — resets progress state and goes back to form ───────────────────
  const handleReset = useCallback(() => {
    abortRef.current?.()
    stopLatencyTicker()
    setInProgress(false)
    setAgentStates({})
    setCostCny(0)
    setLatencyMs(0)
    setCriticScores(null)
    setProgressError(null)
    setStreamingMd('')
    setTimelineEntries([])
    setSubmitting(false)
  }, [stopLatencyTicker])

  // ── Form submit ─────────────────────────────────────────────────────────────
  const handleSubmit = useCallback(
    (values: FormValues) => {
      setSubmitting(true)
      setInProgress(true)
      setAgentStates({ 'Planner': { name: 'Planner', status: 'running' } })
      setCostCny(0)
      setLatencyMs(0)
      setCriticScores(null)
      setProgressError(null)
      setStreamingMd('')
      setTimelineEntries([])

      const req: ResearchRequest = {
        target_ts_code: values.target_ts_code.trim(),
        client_total_aum: values.client_total_aum,
        client_existing_position: values.client_existing_position,
        investment_objective: values.investment_objective,
        investment_horizon: values.investment_horizon,
        risk_tolerance: values.risk_tolerance,
        user_message: values.user_message?.trim() || undefined,
      }

      // Abort any in-flight request before starting a new one.
      abortRef.current?.()
      startLatencyTicker()

      const { abort } = submitResearch(
        req,
        (ev: SSEResearchEvent) => {
          // Update agent states
          setAgentStates((prev) => applySSEToAgentStates(prev, ev))

          // Push research log entry (业务化研究日志 — 不显示 agent 名)
          {
            const elapsedSec = (Date.now() - startTimeRef.current) / 1000
            let entry: TimelineEntry | null = null
            if (ev.type === 'plan') {
              // Backend summary already has emoji prefix (e.g. "📋 已拆解为 N 个研究维度")
              const summary = (ev.data['summary'] as string | undefined) ?? '📋 正在规划研究路径...'
              const subtasks = (ev.data['subtasks'] as string[] | undefined) ?? []
              // agentLabel kept for AgentStatusSidebar internal use, not displayed in log
              entry = { elapsedSec, agentLabel: 'Planner', summary, bullets: subtasks, done: true }
            } else if (ev.type === 'data_progress') {
              const summary = (ev.data['summary'] as string | undefined) ?? '✅ 数据采集完成'
              const tools = (ev.data['tools'] as string[] | undefined) ?? []
              entry = { elapsedSec, agentLabel: 'DataCollector', summary, bullets: tools, done: true }
            } else if (ev.type === 'insight') {
              const summary = (ev.data['summary'] as string | undefined) ?? '💡 分析完成'
              const findings = (ev.data['findings'] as string[] | undefined) ?? []
              entry = { elapsedSec, agentLabel: 'Analyst', summary, bullets: findings, done: true }
            } else if (ev.type === 'report_chunk') {
              // Only push once (first report_chunk); backend now sets summary field
              const summary = (ev.data['summary'] as string | undefined) ?? '📝 报告撰写完成'
              entry = { elapsedSec, agentLabel: 'Writer', summary, done: true }
            } else if (ev.type === 'critic_score') {
              const scorer = (ev.data['scorer'] as string | undefined) ?? ''
              const isAggregate = scorer === 'aggregate'
              if (isAggregate) {
                // Only aggregate emit goes into the research log
                const summary = (ev.data['summary'] as string | undefined) ?? '🔬 评审完成'
                entry = { elapsedSec, agentLabel: 'Critic', summary, done: true }
              }
              // Individual scorer events are skipped in the research log
              // (they show up in the AgentStatusSidebar tech panel)
            } else if (ev.type === 'done') {
              entry = { elapsedSec, agentLabel: 'done', summary: '✅ 报告生成完毕，即将跳转...', done: true }
            }
            if (entry !== null) {
              // For report_chunk: only push the first one to avoid duplicates
              if (ev.type === 'report_chunk') {
                setTimelineEntries((prev) => {
                  const hasWriter = prev.some((e) => e.agentLabel === 'Writer')
                  return hasWriter ? prev : [...prev, entry as TimelineEntry]
                })
              } else {
                setTimelineEntries((prev) => [...prev, entry as TimelineEntry])
              }
            }
          }

          // spec § 4.3: accumulate streaming markdown from writer node
          if (ev.type === 'report_chunk') {
            const chunk = (ev.data['chunk'] as string | undefined) ?? ''
            if (chunk) {
              setStreamingMd((prev) => prev + chunk)
            }
          }

          // Extract cost if present in any event
          if (ev.data && typeof ev.data['cost_cny'] === 'number') {
            setCostCny(ev.data['cost_cny'] as number)
          }

          // Critic score event — only update scores from aggregate node (has real scores)
          if (ev.type === 'critic_score' && ev.data) {
            const scorer = (ev.data['scorer'] as string | undefined) ?? ''
            const isAggregate = scorer === 'aggregate'
            if (isAggregate) {
              // New format: scores is a dict of dimension → score, overall is float
              const scoresRaw = (ev.data['scores'] as Record<string, number> | undefined) ?? {}
              const overall = (ev.data['overall'] as number | undefined) ?? 0
              // Map to CriticScores interface (best-effort mapping from new 6-dim schema)
              const scores: CriticScores = {
                data_quality: scoresRaw['factuality'] ?? 0,
                logical_coherence: scoresRaw['insight'] ?? 0,
                client_fit: scoresRaw['input_context_appropriateness'] ?? 0,
                risk_disclosure: scoresRaw['coverage'] ?? 0,
                regulatory_compliance: scoresRaw['conciseness'] ?? 0,
                actionability: scoresRaw['structure'] ?? 0,
                total: overall,
              }
              setCriticScores(scores)
            }
          }

          // Done → navigate
          if (ev.type === 'done' && ev.data && 'request_id' in ev.data) {
            const backendId = ev.data.request_id as string
            if (backendId) {
              stopLatencyTicker()
              setSubmitting(false)
              void navigate(`/research/${backendId}`, { state: { req } })
            }
          }

          // Error event
          if (ev.type === 'error') {
            stopLatencyTicker()
            setSubmitting(false)
            const isDegraded = (ev.data['degraded'] as boolean | undefined) === true
            if (isDegraded) {
              setProgressError({
                type: 'degraded_mode',
                message: (ev.data['message'] as string | undefined) ?? '工具降级',
                degradedTool: ev.data['tool'] as string | undefined,
              })
            } else {
              setProgressError({
                type: 'agent_crash',
                message: (ev.data['message'] as string | undefined) ?? '尽调过程出错，请重试',
                requestId: ev.data['request_id'] as string | undefined,
              })
            }
          }
        },
        (err: Error) => {
          stopLatencyTicker()
          setSubmitting(false)
          const isCostExceeded = err.message.toLowerCase().includes('cost') ||
            err.message.includes('budget')
          if (isCostExceeded) {
            setProgressError({
              type: 'cost_exceeded',
              message: err.message,
            })
          } else if (err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) {
            setProgressError({
              type: 'sse_disconnected',
              message: err.message,
            })
          } else {
            void window.$app.message.error(`提交失败：${err.message}`)
            setProgressError({
              type: 'agent_crash',
              message: err.message,
            })
          }
        },
      )

      abortRef.current = abort
    },
    [navigate, startLatencyTicker, stopLatencyTicker],
  )

  // ── Render: progress overlay ─────────────────────────────────────────────
  if (inProgress) {
    const latencySec = (latencyMs / 1000).toFixed(1)
    // TODO(v0.8.5): attach cumulative cost from LLMService; currently no per-request
    // cost accumulator is exposed from the backend streaming path. Cost stays ¥0.
    const costDisplay = costCny.toFixed(4)

    return (
      <div
        style={{
          padding: '32px 24px 0',
          backgroundColor: TOKEN.pageBg,
          minHeight: '100%',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Header */}
        <div style={{ marginBottom: 20 }}>
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
            尽调报告生成中
          </Title>
          <Text
            style={{
              fontSize: 13,
              color: TOKEN.textTertiary,
              marginTop: 4,
              display: 'block',
            }}
          >
            AI 正在采集数据、分析财务与行业信息，请稍候...
          </Text>
        </div>

        {/* Error banner (degraded mode can show while still running) */}
        {progressError && (
          <div style={{ marginBottom: 16 }}>
            <ErrorBanner
              error={progressError}
              onRetry={handleReset}
              onDismiss={() => setProgressError(null)}
            />
          </div>
        )}

        {/* Main progress area — single column: research log + expandable tech panel */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
            maxWidth: 760,
          }}
        >
          {/* Main area: Business-friendly research log timeline */}
          <ProgressTimeline
            entries={timelineEntries}
            style={{ flex: 1 }}
          />

          {/* Streaming markdown preview — shown once writer completes (spec § 4.3) */}
          {streamingMd && (
            <div
              style={{
                backgroundColor: TOKEN.cardBg,
                border: `1px solid ${TOKEN.borderColor}`,
                borderRadius: 10,
                padding: '16px 20px',
              }}
            >
              <div
                style={{
                  fontSize: 12,
                  color: TOKEN.textTertiary,
                  fontWeight: 600,
                  letterSpacing: '0.06em',
                  textTransform: 'uppercase',
                  marginBottom: 8,
                }}
              >
                报告预览
              </div>
              <div
                style={{
                  maxHeight: '40vh',
                  overflowY: 'auto',
                  fontSize: 13,
                  lineHeight: 1.7,
                  color: TOKEN.textPrimary,
                }}
              >
                <Markdown value={streamingMd} />
              </div>
            </div>
          )}

          {/* 技术细节 expandable panel (collapsed by default)
              面试官 / 架构透明: 5-agent pipeline + 6-dim Critic 评分 */}
          <Collapse
            size="small"
            style={{ borderColor: TOKEN.borderColor, backgroundColor: TOKEN.pageBg }}
            defaultActiveKey={[]}
            items={[
              {
                key: 'tech',
                label: (
                  <span style={{ fontSize: 12, color: TOKEN.textSecondary, fontWeight: 600 }}>
                    技术细节 — 5-agent 架构 + Critic 评分
                  </span>
                ),
                children: (
                  <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                    {/* Agent pipeline */}
                    <div style={{ flex: '0 0 200px', minWidth: 180 }}>
                      <AgentStatusSidebar
                        agentStates={agentStates}
                        style={{ border: 'none', padding: 0, borderRadius: 0, minWidth: 'unset' }}
                      />
                    </div>
                    {/* 6-dim Critic scores (shown after critic aggregate fires) */}
                    {criticScores && (
                      <div style={{ flex: 1, minWidth: 220 }}>
                        <CostLatencyMetrics
                          costCny={costCny}
                          latencyMs={latencyMs}
                          criticScores={criticScores}
                          style={{ border: 'none', padding: 0, borderRadius: 0 }}
                        />
                      </div>
                    )}
                  </div>
                ),
              },
            ]}
          />

          {/* Cancel / retry button */}
          <div style={{ paddingBottom: 16 }}>
            <Button
              onClick={handleReset}
              disabled={submitting && !progressError}
              style={{
                borderColor: TOKEN.borderColor,
                color: TOKEN.textSecondary,
                fontSize: 13,
              }}
            >
              {progressError ? '返回表单' : '取消'}
            </Button>
          </div>
        </div>

        {/* Bottom status bar — 1 line: latency · cost / budget */}
        <div
          style={{
            position: 'sticky',
            bottom: 0,
            backgroundColor: TOKEN.pageBg,
            borderTop: `1px solid ${TOKEN.borderColor}`,
            padding: '8px 0',
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            fontSize: 12,
            color: TOKEN.textTertiary,
          }}
        >
          <span>
            已用{' '}
            <span style={{ fontFamily: '"SF Mono", Consolas, monospace', color: TOKEN.textSecondary }}>
              {latencySec}s
            </span>
          </span>
          <span style={{ color: TOKEN.borderColor }}>·</span>
          <span>
            费用{' '}
            <span style={{ fontFamily: '"SF Mono", Consolas, monospace', color: TOKEN.textSecondary }}>
              ¥{costDisplay}
            </span>
            {' / ¥20'}
            {/* TODO(v0.8.5): wire cumulative cost from backend SSE cost_cny field */}
          </span>
        </div>
      </div>
    )
  }

  // ── Render: form ─────────────────────────────────────────────────────────
  return (
    <div
      style={{
        padding: '32px 24px',
        backgroundColor: TOKEN.pageBg,
        minHeight: '100%',
      }}
    >
      {/* ── Page header ── */}
      <div style={{ marginBottom: 28 }}>
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
          新建投资尽调
        </Title>
        <Text
          style={{
            fontSize: 13,
            color: TOKEN.textTertiary,
            marginTop: 4,
            display: 'block',
          }}
        >
          填写标的信息与客户画像，AI 将生成结构化尽调报告
        </Text>
      </div>

      {/* ── Form card ── */}
      <Card
        style={{
          maxWidth: 680,
          borderColor: TOKEN.borderColor,
          borderRadius: 10,
          backgroundColor: TOKEN.cardBg,
        }}
        styles={{ body: { padding: '28px 32px' } }}
      >
        <Form<FormValues>
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          requiredMark="optional"
          size="middle"
        >
          {/* ── 1. 标的代码 ── */}
          <Form.Item
            name="target_ts_code"
            label="标的代码"
            rules={[
              { required: true, message: '请输入股票代码，如 600519.SH' },
              {
                pattern: /^[0-9]{6}\.(SH|SZ|BJ)$/i,
                message: '格式应为 6 位数字 + .SH/.SZ/.BJ，如 600519.SH',
              },
            ]}
            extra={
              <span style={{ fontSize: 12, color: TOKEN.textTertiary }}>
                输入股票名称或代码前缀可联想补全
              </span>
            }
          >
            <AutoComplete
              options={autoCompleteOptions}
              onSearch={(val) => {
                void handleTsCodeSearch(val)
              }}
              placeholder="如 600519.SH 或 茅台"
              allowClear
              filterOption={false}
              style={{ width: '100%' }}
            />
          </Form.Item>

          {/* ── 2. 客户总 AUM ── */}
          <Form.Item
            name="client_total_aum"
            label="客户总 AUM（元）"
            rules={[
              { required: true, message: '请输入客户总资产管理规模' },
              {
                type: 'number',
                min: 1,
                message: 'AUM 必须大于 0',
              },
            ]}
          >
            <InputNumber
              style={{ width: '100%' }}
              placeholder="如 5000000（500 万元）"
              min={1}
              precision={0}
              formatter={(v) =>
                v ? `¥ ${String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ',')}` : ''
              }
              parser={(v) => Number(String(v).replace(/¥\s?|(,*)/g, '')) as number}
            />
          </Form.Item>

          {/* ── 3. 现有持仓（可选）── */}
          <Form.Item
            name="client_existing_position"
            label="现有持仓（元，可选）"
            rules={[
              {
                type: 'number',
                min: 0,
                message: '持仓金额不能为负数',
              },
            ]}
          >
            <InputNumber
              style={{ width: '100%' }}
              placeholder="若客户已持有该标的，请填写现有持仓市值"
              min={0}
              precision={0}
              formatter={(v) =>
                v ? `¥ ${String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ',')}` : ''
              }
              parser={(v) => Number(String(v).replace(/¥\s?|(,*)/g, '')) as number}
            />
          </Form.Item>

          {/* ── 4. 投资目标 ── */}
          <Form.Item
            name="investment_objective"
            label="投资目标"
            rules={[{ required: true, message: '请选择投资目标' }]}
          >
            <Select
              placeholder="请选择投资目标"
              options={OBJECTIVE_OPTIONS}
            />
          </Form.Item>

          {/* ── 5. 投资期限 ── */}
          <Form.Item
            name="investment_horizon"
            label="投资期限"
            rules={[{ required: true, message: '请选择投资期限' }]}
          >
            <Select
              placeholder="请选择投资期限"
              options={HORIZON_OPTIONS}
            />
          </Form.Item>

          {/* ── 6. 风险承受度 ── */}
          <Form.Item
            name="risk_tolerance"
            label="风险承受度"
            rules={[{ required: true, message: '请选择风险承受度' }]}
          >
            <Select
              placeholder="请选择风险承受度"
              options={TOLERANCE_OPTIONS}
            />
          </Form.Item>

          {/* ── 7. 补充说明（可选）── */}
          <Form.Item
            name="user_message"
            label="补充说明（可选）"
          >
            <TextArea
              placeholder="可输入额外的尽调侧重点、客户特殊情况或其他背景信息..."
              rows={3}
              maxLength={500}
              showCount
            />
          </Form.Item>

          {/* ── Submit ── */}
          <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={submitting}
              icon={<PlusOutlined />}
              style={{
                backgroundColor: TOKEN.accentBlue,
                borderColor: TOKEN.accentBlue,
                height: 40,
                fontSize: 14,
                fontWeight: 500,
                paddingInline: 28,
              }}
            >
              {submitting ? '生成中...' : '开始生成尽调报告'}
            </Button>
            <Button
              style={{ marginLeft: 12, height: 40 }}
              onClick={() => form.resetFields()}
              disabled={submitting}
            >
              重置
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}
