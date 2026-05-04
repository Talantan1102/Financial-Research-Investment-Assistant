/**
 * frontend/src/pages/research/new.tsx
 * B-1 新建尽调表单页面。
 *
 * 两态:
 *   1. form 态  — 6 字段表单
 *   2. progress 态 — submit 后展示 AgentStatusSidebar + CostLatencyMetrics
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
 * SSE event 处理 (C2 进度 UI):
 *   plan          → Planner running
 *   data_progress → DataCollector running + subtask progress
 *   insight       → Analyst running
 *   report_chunk  → Writer running + accumulate streamingMd (spec § 4.3)
 *   critic_score  → Critic done + CriticScores
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
  message,
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
      // DataCollector subtask progress
      const tool = (ev.data['tool'] as string | undefined) ?? 'unknown'
      const toolDone = (ev.data['done'] as boolean | undefined) ?? false
      const existing = prev['DataCollector']
      const subtasks = existing?.subtasks ? [...existing.subtasks] : []
      const idx = subtasks.findIndex((s) => s.label === tool)
      if (idx === -1) {
        subtasks.push({ label: tool, status: toolDone ? 'done' : 'running' })
      } else {
        subtasks[idx] = { ...subtasks[idx], status: toolDone ? 'done' : 'running' }
      }
      next['DataCollector'] = {
        name: 'DataCollector',
        status: 'running',
        subtasks,
      }
      break
    }

    case 'insight':
      // DataCollector done, Analyst running
      next['DataCollector'] = {
        ...prev['DataCollector'],
        name: 'DataCollector',
        status: 'done',
      }
      next['Analyst'] = { name: 'Analyst', status: 'running' }
      break

    case 'report_chunk':
      // Analyst done (first chunk), Writer running
      if (prev['Analyst']?.status !== 'done') {
        next['Analyst'] = { name: 'Analyst', status: 'done' }
      }
      next['Writer'] = { name: 'Writer', status: 'running' }
      break

    case 'critic_score':
      // Writer done, Critic done
      next['Writer'] = { ...prev['Writer'], name: 'Writer', status: 'done' }
      next['Critic'] = { name: 'Critic', status: 'done' }
      break

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

          // Critic score event
          if (ev.type === 'critic_score' && ev.data) {
            const scores: CriticScores = {
              data_quality: (ev.data['data_quality'] as number) ?? 0,
              logical_coherence: (ev.data['logical_coherence'] as number) ?? 0,
              client_fit: (ev.data['client_fit'] as number) ?? 0,
              risk_disclosure: (ev.data['risk_disclosure'] as number) ?? 0,
              regulatory_compliance: (ev.data['regulatory_compliance'] as number) ?? 0,
              actionability: (ev.data['actionability'] as number) ?? 0,
              total: (ev.data['total'] as number) ?? 0,
            }
            setCriticScores(scores)
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
            void message.error(`提交失败：${err.message}`)
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
    return (
      <div
        style={{
          padding: '32px 24px',
          backgroundColor: TOKEN.pageBg,
          minHeight: '100%',
        }}
      >
        {/* Header */}
        <div style={{ marginBottom: 24 }}>
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

        {/* Progress area */}
        <div
          style={{
            display: 'flex',
            gap: 16,
            alignItems: 'flex-start',
            flexWrap: 'wrap',
          }}
        >
          {/* Agent sidebar */}
          <AgentStatusSidebar
            agentStates={agentStates}
            style={{ flex: '0 0 220px' }}
          />

          {/* Cost + latency */}
          <CostLatencyMetrics
            costCny={costCny}
            latencyMs={latencyMs}
            criticScores={criticScores}
            style={{ flex: '0 0 220px' }}
          />

          {/* Main area: streaming markdown (spec § 4.3) or placeholder */}
          <div
            style={{
              flex: '1 1 300px',
              backgroundColor: TOKEN.cardBg,
              border: `1px solid ${TOKEN.borderColor}`,
              borderRadius: 10,
              padding: '16px 20px',
              minHeight: 180,
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
            }}
          >
            <div
              style={{
                fontSize: 12,
                color: TOKEN.textTertiary,
                fontWeight: 600,
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
              }}
            >
              {streamingMd ? '报告预览' : '生成提示'}
            </div>
            {streamingMd ? (
              <div
                style={{
                  maxHeight: '60vh',
                  overflowY: 'auto',
                  fontSize: 13,
                  lineHeight: 1.7,
                  color: TOKEN.textPrimary,
                }}
              >
                <Markdown value={streamingMd} />
              </div>
            ) : (
              <div style={{ fontSize: 13, color: TOKEN.textSecondary, lineHeight: 1.7 }}>
                <p style={{ margin: 0 }}>
                  报告通常需要 2–5 分钟完成。生成完毕后将自动跳转到报告页面。
                </p>
                <p style={{ margin: '8px 0 0' }}>
                  如需终止并重新填写，请点击下方"取消"按钮。
                </p>
              </div>
            )}
            <div style={{ marginTop: 'auto' }}>
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
        bodyStyle={{ padding: '28px 32px' }}
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
