/**
 * frontend/src/pages/research/new.tsx
 * B-1 新建尽调表单页面。
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
 * 提交 → POST /api/v0.5/research SSE → navigate 到 /research/:id
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
import type { TsCodeSuggestion } from '@/api/research'
import {
  INVESTMENT_HORIZON_LABELS,
  INVESTMENT_OBJECTIVE_LABELS,
  RISK_TOLERANCE_LABELS,
} from '@/types/research'
import type {
  InvestmentHorizon,
  InvestmentObjective,
  ResearchRequest,
  RiskTolerance,
  SSEResearchEvent,
} from '@/types/research'

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

// ── Component ─────────────────────────────────────────────────────────────────

export default function ResearchNew() {
  const navigate = useNavigate()
  const [form] = Form.useForm<FormValues>()
  const [submitting, setSubmitting] = useState(false)
  const [suggestions, setSuggestions] = useState<TsCodeSuggestion[]>([])
  const abortRef = useRef<(() => void) | null>(null)

  // ── AutoComplete: fetch suggestions on input change ─────────────────────────
  const handleTsCodeSearch = useCallback(async (value: string) => {
    if (!value || value.length < 1) {
      setSuggestions([])
      return
    }
    try {
      const results = await autocompleteTsCode(value)
      setSuggestions(results)
    } catch {
      // Network errors silently ignored; user can type ts_code manually.
      setSuggestions([])
    }
  }, [])

  const autoCompleteOptions = suggestions.map((s) => ({
    value: s.ts_code,
    label: `${s.name}（${s.ts_code}）`,
  }))

  // ── Form submit ─────────────────────────────────────────────────────────────
  const handleSubmit = useCallback(
    async (values: FormValues) => {
      setSubmitting(true)

      const req: ResearchRequest = {
        target_ts_code: values.target_ts_code.trim(),
        client_total_aum: values.client_total_aum,
        client_existing_position: values.client_existing_position,
        investment_objective: values.investment_objective,
        investment_horizon: values.investment_horizon,
        risk_tolerance: values.risk_tolerance,
        user_message: values.user_message?.trim() || undefined,
      }

      // We use submitResearch and navigate to the report page as soon as the
      // first event arrives (request_id is embedded in the done event).
      // For now we navigate eagerly with a generated local ID and let the
      // report page pick up the SSE stream.
      //
      // Strategy: generate a client-side run ID from timestamp, start the
      // stream in background, navigate to /research/:id immediately so the
      // report page (Task 6) can hook into the same stream via context or
      // re-subscribe. This matches spec § 4.2 "提交 → 跳 /research/:id".
      //
      // The run ID used here is a short slug the report page uses as
      // session_id for the SSE subscription re-open if needed.
      const runId = `run-${Date.now().toString(36)}`

      // Abort any in-flight request before starting a new one.
      abortRef.current?.()

      let navigated = false

      const { abort } = submitResearch(
        req,
        (ev: SSEResearchEvent) => {
          if (!navigated) {
            navigated = true
            void navigate(`/research/${runId}`, {
              state: { req, runId },
            })
          }
          // Subsequent events handled by the report page (Task 6).
          if (ev.type === 'error') {
            void message.error('尽调过程出错，请重试')
          }
        },
        (err: Error) => {
          setSubmitting(false)
          void message.error(`提交失败：${err.message}`)
        },
      )

      abortRef.current = abort

      // Navigate immediately even if stream takes time to start.
      if (!navigated) {
        navigated = true
        void navigate(`/research/${runId}`, {
          state: { req, runId },
        })
      }

      // Note: setSubmitting(false) is handled by the report page after done event.
    },
    [navigate],
  )

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
              parser={(v) => Number(String(v).replace(/¥\s?|(,*)/g, '')) as 5000000}
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
              parser={(v) => Number(String(v).replace(/¥\s?|(,*)/g, '')) as 0}
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
