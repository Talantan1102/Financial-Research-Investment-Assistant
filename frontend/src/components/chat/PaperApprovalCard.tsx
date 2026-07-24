import { previewPaperOrder } from '@/api/paperTrading'
import type {
  ApprovalResumeResponse,
  ApprovalToolCall,
  EditableApprovalRequest,
  PaperOrderDraft,
  PaperOrderPreview,
} from '@/types/paper-trading'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import styles from './PaperApprovalCard.module.scss'

const PAPER_WRITES = new Set([
  'place_paper_order',
  'cancel_paper_order',
  'reset_paper_account',
])

type ResumeResult = { ok: boolean; error?: string }

interface EditablePaperCall {
  call: ApprovalToolCall
  arguments: Record<string, unknown>
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function parseArguments(
  value: ApprovalToolCall['arguments'],
): Record<string, unknown> | null {
  if (typeof value !== 'string') return asRecord(value)
  try {
    return asRecord(JSON.parse(value))
  } catch {
    return null
  }
}

function editablePaperCall(
  request: Record<string, unknown>,
): EditablePaperCall | null {
  if (!Array.isArray(request.tool_calls) || request.tool_calls.length !== 1)
    return null
  if (
    !Array.isArray(request.editable_tool_call_ids) ||
    request.editable_tool_call_ids.length !== 1
  )
    return null
  const rawCall = asRecord(request.tool_calls[0])
  if (!rawCall) return null
  const id = typeof rawCall.id === 'string' ? rawCall.id : null
  const name = typeof rawCall.name === 'string' ? rawCall.name : null
  if (
    !id ||
    !name ||
    request.editable_tool_call_ids[0] !== id ||
    !PAPER_WRITES.has(name)
  ) {
    return null
  }
  const call: ApprovalToolCall = {
    id,
    name,
    arguments:
      typeof rawCall.arguments === 'string'
        ? rawCall.arguments
        : (asRecord(rawCall.arguments) ?? {}),
  }
  const parsed = parseArguments(call.arguments)
  return parsed ? { call, arguments: parsed } : { call, arguments: {} }
}

function parseOrderDraft(
  value: Record<string, unknown>,
): PaperOrderDraft | null {
  const side = value.side
  const orderType = value.order_type
  const limitPrice = value.limit_price
  if (
    (side !== 'buy' && side !== 'sell') ||
    (orderType !== 'market' && orderType !== 'limit') ||
    typeof value.ts_code !== 'string' ||
    typeof value.name !== 'string' ||
    typeof value.quantity !== 'number' ||
    !Number.isInteger(value.quantity) ||
    value.quantity <= 0 ||
    (limitPrice !== null &&
      typeof limitPrice !== 'string' &&
      typeof limitPrice !== 'number')
  )
    return null
  if (
    orderType === 'limit' &&
    (limitPrice === null || String(limitPrice).trim() === '')
  )
    return null
  if (orderType === 'market' && limitPrice !== null && limitPrice !== undefined)
    return null
  return {
    side,
    ts_code: value.ts_code,
    name: value.name,
    quantity: value.quantity,
    order_type: orderType,
    limit_price: limitPrice == null ? null : String(limitPrice),
  }
}

function canonicalJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalJsonValue)
  const record = asRecord(value)
  if (!record) return value
  return Object.fromEntries(
    Object.keys(record)
      .sort()
      .map((key) => [key, canonicalJsonValue(record[key])]),
  )
}

function approvalIdentity(selected: EditablePaperCall | null): string {
  if (!selected) return 'unsupported'
  const parsed = parseArguments(selected.call.arguments)
  return JSON.stringify([
    selected.call.id,
    selected.call.name,
    canonicalJsonValue(parsed ?? selected.call.arguments),
  ])
}

function isAbortError(cause: unknown): boolean {
  return (
    (cause instanceof DOMException && cause.name === 'AbortError') ||
    (cause instanceof Error && cause.name === 'AbortError')
  )
}

function money(value: string): string {
  const numeric = Number(value)
  return Number.isFinite(numeric)
    ? new Intl.NumberFormat('zh-CN', {
        style: 'currency',
        currency: 'CNY',
        minimumFractionDigits: 2,
      })
        .format(numeric)
        .replace('CN¥', '¥')
    : value
}

function paperTitle(name: string, args: Record<string, unknown>): string {
  if (name === 'place_paper_order')
    return args.side === 'sell' ? '模拟卖出审批' : '模拟买入审批'
  if (name === 'cancel_paper_order') return '撤销模拟订单'
  return '重置模拟账户'
}

export interface PaperApprovalCardProps {
  request: EditableApprovalRequest | Record<string, unknown>
  onResume: (
    response: ApprovalResumeResponse,
  ) => Promise<ResumeResult> | ResumeResult
  disabled?: boolean
}

export function PaperApprovalCard({
  request,
  onResume,
  disabled = false,
}: PaperApprovalCardProps) {
  const selected = useMemo(() => editablePaperCall(request), [request])
  const requestIdentity = approvalIdentity(selected)
  const original = useMemo(
    () => (selected ? parseArguments(selected.call.arguments) : null),
    [selected],
  )
  const initialOrder = useMemo(
    () =>
      selected?.call.name === 'place_paper_order' && original
        ? parseOrderDraft(original)
        : null,
    [original, selected],
  )
  const [draft, setDraft] = useState<PaperOrderDraft | null>(initialOrder)
  const [otherDraft, setOtherDraft] = useState<Record<string, unknown>>(
    original ?? {},
  )
  const [preview, setPreview] = useState<PaperOrderPreview | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const previewSequence = useRef(0)
  const revision = useRef(0)
  const requestGeneration = useRef(0)
  const resetPayload = useRef({ initialOrder, original })
  const previewController = useRef<AbortController | null>(null)
  const mounted = useRef(true)
  const submitLocked = useRef(false)
  resetPayload.current = { initialOrder, original }

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      previewController.current?.abort()
      previewController.current = null
      previewSequence.current += 1
    }
  }, [])

  useLayoutEffect(() => {
    requestGeneration.current += 1
    previewController.current?.abort()
    previewController.current = null
    previewSequence.current += 1
    submitLocked.current = false
    setDraft(resetPayload.current.initialOrder)
    setOtherDraft(resetPayload.current.original ?? {})
    setPreview(null)
    setPreviewing(false)
    setSubmitting(false)
    setDirty(false)
    setError(null)
    revision.current += 1
  }, [requestIdentity])

  const respond = async (response: ApprovalResumeResponse) => {
    if (submitLocked.current || disabled) return
    const generation = requestGeneration.current
    submitLocked.current = true
    setSubmitting(true)
    setError(null)
    try {
      const result = await onResume(response)
      if (
        generation === requestGeneration.current &&
        !result.ok &&
        mounted.current
      ) {
        setError(result.error ?? '操作未提交，请重试。')
      }
    } catch (cause) {
      if (generation === requestGeneration.current && mounted.current) {
        setError(
          cause instanceof Error ? cause.message : '操作未提交，请重试。',
        )
      }
    } finally {
      if (generation === requestGeneration.current) {
        submitLocked.current = false
        if (mounted.current) setSubmitting(false)
      }
    }
  }

  if (!selected || !original) {
    return (
      <section className={styles.card} role="region" aria-label="模拟交易审批">
        <div className={styles.error} role="alert">
          交易参数无法读取，请拒绝后重新发起。
        </div>
        <button
          type="button"
          className={styles.reject}
          disabled={disabled || submitting}
          onClick={() => {
            void respond({ approved: false })
          }}
        >
          拒绝交易
        </button>
      </section>
    )
  }

  const isOrder = selected.call.name === 'place_paper_order'
  const validOrder =
    draft !== null &&
    draft.quantity > 0 &&
    (draft.order_type === 'market' || Boolean(draft.limit_price?.trim()))
  const validOther =
    selected.call.name === 'cancel_paper_order'
      ? typeof otherDraft.order_id === 'string' &&
        /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
          otherDraft.order_id,
        )
      : selected.call.name === 'reset_paper_account'
        ? /^\d{1,16}(?:\.\d{1,2})?$/.test(
            String(otherDraft.initial_cash ?? ''),
          ) && Number(otherDraft.initial_cash) > 0
        : true
  const previewCurrent = isOrder && preview !== null && !dirty

  const updateOrder = <K extends keyof PaperOrderDraft>(
    key: K,
    value: PaperOrderDraft[K],
  ) => {
    setDraft((current) => (current ? { ...current, [key]: value } : current))
    revision.current += 1
    setDirty(true)
    setPreview(null)
    setError(null)
  }

  const updateOther = (key: string, value: string) => {
    setOtherDraft((current) => ({ ...current, [key]: value }))
    revision.current += 1
    setDirty(true)
    setError(null)
  }

  const calculatePreview = async () => {
    if (!draft || !validOrder) return
    const sequence = ++previewSequence.current
    const requestedRevision = revision.current
    previewController.current?.abort()
    const controller = new AbortController()
    previewController.current = controller
    setPreviewing(true)
    setError(null)
    try {
      const next = await previewPaperOrder(
        { draft },
        { signal: controller.signal },
      )
      if (
        mounted.current &&
        sequence === previewSequence.current &&
        requestedRevision === revision.current
      ) {
        setPreview(next)
        setDirty(false)
      }
    } catch (cause) {
      if (
        !isAbortError(cause) &&
        mounted.current &&
        sequence === previewSequence.current
      ) {
        setPreview(null)
        setError(
          cause instanceof Error ? cause.message : '交易预览失败，请重试。',
        )
      }
    } finally {
      if (previewController.current === controller) {
        previewController.current = null
      }
      if (mounted.current && sequence === previewSequence.current) {
        setPreviewing(false)
      }
    }
  }

  const effectiveArguments: Record<string, unknown> = draft ?? otherDraft
  const approveDisabled =
    disabled ||
    submitting ||
    (isOrder ? !validOrder || !previewCurrent : !validOther)
  const approveLabel =
    selected.call.name === 'place_paper_order'
      ? draft?.side === 'sell'
        ? '确认卖出'
        : '确认买入'
      : selected.call.name === 'cancel_paper_order'
        ? '确认撤单'
        : '确认重置'

  return (
    <section className={styles.card} role="region" aria-label="模拟交易审批">
      <header className={styles.header}>
        <div>
          <div className={styles.eyebrow}>需要你的确认</div>
          <h3>{paperTitle(selected.call.name, effectiveArguments)}</h3>
        </div>
        <span className={styles.badge}>模拟账户</span>
      </header>

      <div className={styles.diff} aria-label="原稿与最终参数">
        <div className={styles.original}>
          <span>Agent 原稿</span>
          <code>{JSON.stringify(original)}</code>
        </div>
        <span className={styles.arrow} aria-hidden="true">
          →
        </span>
        <div className={styles.final}>
          <span>最终参数</span>
          <code>{JSON.stringify(effectiveArguments)}</code>
        </div>
      </div>

      {isOrder && draft ? (
        <div className={styles.fields}>
          <label>
            方向
            <select
              aria-label="方向"
              value={draft.side}
              disabled={disabled || submitting}
              onChange={(event) =>
                updateOrder(
                  'side',
                  event.target.value as PaperOrderDraft['side'],
                )
              }
            >
              <option value="buy">买入</option>
              <option value="sell">卖出</option>
            </select>
          </label>
          <label>
            数量
            <input
              aria-label="数量"
              inputMode="numeric"
              type="number"
              min={1}
              step={1}
              value={draft.quantity || ''}
              disabled={disabled || submitting}
              onChange={(event) =>
                updateOrder('quantity', Number(event.target.value))
              }
            />
          </label>
          <label>
            订单类型
            <select
              aria-label="订单类型"
              value={draft.order_type}
              disabled={disabled || submitting}
              onChange={(event) => {
                const orderType = event.target
                  .value as PaperOrderDraft['order_type']
                setDraft((current) =>
                  current
                    ? {
                        ...current,
                        order_type: orderType,
                        limit_price:
                          orderType === 'market'
                            ? null
                            : (current.limit_price ?? ''),
                      }
                    : current,
                )
                revision.current += 1
                setDirty(true)
                setPreview(null)
              }}
            >
              <option value="market">市价</option>
              <option value="limit">限价</option>
            </select>
          </label>
          {draft.order_type === 'limit' ? (
            <label>
              限价
              <input
                aria-label="限价"
                inputMode="decimal"
                value={draft.limit_price ?? ''}
                disabled={disabled || submitting}
                onChange={(event) =>
                  updateOrder('limit_price', event.target.value)
                }
              />
            </label>
          ) : null}
        </div>
      ) : selected.call.name === 'reset_paper_account' ? (
        <label className={styles.singleField}>
          重置后的初始资金
          <input
            aria-label="重置后的初始资金"
            inputMode="decimal"
            value={String(otherDraft.initial_cash ?? '')}
            disabled={disabled || submitting}
            onChange={(event) =>
              updateOther('initial_cash', event.target.value)
            }
          />
        </label>
      ) : (
        <p className={styles.orderId}>
          订单编号 <code>{String(otherDraft.order_id ?? '')}</code>
        </p>
      )}

      {isOrder ? (
        <div className={styles.preview} aria-live="polite">
          {previewCurrent && preview ? (
            <>
              <span className={styles.previewReady}>预览有效</span>
              <strong>{money(preview.estimated_cash_required)}</strong>
              <small>预计占用资金 · 规则 {preview.rules_version}</small>
            </>
          ) : (
            <>
              <span className={styles.previewPending}>
                {previewing
                  ? '正在更新预览…'
                  : dirty
                    ? '参数已修改，请重新预览'
                    : '批准前请先预览'}
              </span>
              <small>预览不会创建订单，也不会冻结资金或股份</small>
            </>
          )}
        </div>
      ) : null}

      {error ? (
        <div className={styles.error} role="alert">
          {error}
        </div>
      ) : null}
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.reject}
          disabled={disabled || submitting}
          onClick={() => {
            void respond({ approved: false })
          }}
        >
          拒绝交易
        </button>
        {isOrder ? (
          <button
            type="button"
            disabled={disabled || submitting || !validOrder}
            onClick={() => {
              void calculatePreview()
            }}
          >
            {dirty || preview ? '重新预览' : '预览交易'}
          </button>
        ) : null}
        <button
          type="button"
          className={styles.approve}
          disabled={approveDisabled}
          onClick={() => {
            void respond({
              approved: true,
              edited_arguments: { [selected.call.id]: effectiveArguments },
            })
          }}
        >
          {submitting ? '提交中…' : approveLabel}
        </button>
      </div>
    </section>
  )
}

PaperApprovalCard.supports = (request: Record<string, unknown>): boolean =>
  editablePaperCall(request) !== null
