import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChatMessage } from '@/types/chat'
import type { ApprovalPayload, OrderDraft, OrderPreview, OrderStatus } from '@/types/paper-trading'
import {
  confirmCancel,
  confirmOrder,
  confirmReset,
  getOrder,
  previewOrder,
} from '@/api/paperTrading'
import styles from './PaperApprovalCard.module.scss'

const TERMINAL: OrderStatus[] = ['filled', 'cancelled', 'expired', 'rejected']

export interface PaperApprovalCardProps { message: ChatMessage }

function payloadOf(message: ChatMessage): ApprovalPayload | null {
  const value = message.tool_call_data
  if (!value || typeof value !== 'object' || !('approval_id' in value)) return null
  return value as ApprovalPayload
}

export function PaperApprovalCard({ message }: PaperApprovalCardProps) {
  const payload = payloadOf(message)
  const initialDraft = useMemo(() => {
    const proposal = payload?.proposal
    return (proposal && 'quantity' in proposal ? proposal : {
      side: 'buy', ts_code: '', name: '', quantity: 0, order_type: 'market', limit_price: null,
    }) as OrderDraft
  }, [payload])
  const [draft, setDraft] = useState<OrderDraft>(initialDraft)
  const [preview, setPreview] = useState(payload?.preview)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<OrderStatus | null>(null)
  const mounted = useRef(true)
  const stopPolling = useRef<(() => void) | null>(null)

  useEffect(() => () => { mounted.current = false; stopPolling.current?.() }, [])
  useEffect(() => { setDraft(initialDraft); setPreview(payload?.preview); setDirty(false) }, [initialDraft, payload?.preview])

  const update = <K extends keyof OrderDraft>(key: K, value: OrderDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }))
    setDirty(true)
  }

  const recalc = async () => {
    if (!payload || payload.approval_type !== 'paper_order') return
    setBusy(true); setError(null)
    try {
      const next = await previewOrder(payload.resource_id, draft)
      if (mounted.current) { setPreview(next); setDirty(false) }
    } catch (err) { if (mounted.current) setError(err instanceof Error ? err.message : '预览失败') }
    finally { if (mounted.current) setBusy(false) }
  }

  const poll = useCallback((orderId: string) => {
    let stopped = false
    let timer: number | undefined
    const tick = async () => {
      try {
        const order = await getOrder(orderId)
        if (stopped || !mounted.current) return
        setStatus(order.status)
        if (!TERMINAL.includes(order.status)) timer = window.setTimeout(tick, 2000)
      } catch (err) { if (!stopped && mounted.current) setError(err instanceof Error ? err.message : '查询订单失败') }
    }
    void tick()
    return () => { stopped = true; if (timer !== undefined) window.clearTimeout(timer) }
  }, [])

  const confirm = async () => {
    if (!payload || dirty || busy) return
    setBusy(true); setError(null)
    try {
      if (payload.approval_type === 'paper_order') {
        const order = await confirmOrder(payload.resource_id, { client_request_id: payload.approval_id, draft })
        setStatus(order.status)
        stopPolling.current?.()
        stopPolling.current = poll(payload.resource_id)
      } else if (payload.approval_type === 'paper_cancel') {
        const order = await confirmCancel(payload.resource_id, { confirmation_id: payload.approval_id })
        setStatus(order.status)
        stopPolling.current?.()
        stopPolling.current = poll(payload.resource_id)
      } else {
        const initial_cash = String((payload.proposal as Record<string, unknown>)?.initial_cash ?? '')
        await confirmReset({ initial_cash, session_id: message.session_id, confirmation_id: payload.approval_id })
        setStatus('filled')
      }
    } catch (err) { if (mounted.current) setError(err instanceof Error ? err.message : '确认失败') }
    finally { if (mounted.current) setBusy(false) }
  }

  if (!payload) return null
  const isOrder = payload.approval_type === 'paper_order'
  const title = isOrder ? (draft.side === 'buy' ? '模拟买入确认' : '模拟卖出确认') : payload.approval_type === 'paper_cancel' ? '取消模拟订单确认' : '重置模拟账户确认'
  return <div className={styles.card} data-testid="paper-approval-card" data-approval-id={payload.approval_id}>
    <h3 className={styles.title}>{title}</h3>
    {isOrder ? <div className={styles.grid}>
      <label className={styles.field}>方向<select aria-label="方向" value={draft.side} onChange={(e) => update('side', e.target.value as OrderDraft['side'])}><option value="buy">买入</option><option value="sell">卖出</option></select></label>
      <label className={styles.field}>股票<input aria-label="股票" value={draft.ts_code} onChange={(e) => update('ts_code', e.target.value)} /></label>
      <label className={styles.field}>数量<input aria-label="数量" type="number" value={draft.quantity} onChange={(e) => update('quantity', Number(e.target.value))} /></label>
      <label className={styles.field}>订单类型<select aria-label="订单类型" value={draft.order_type} onChange={(e) => update('order_type', e.target.value as OrderDraft['order_type'])}><option value="market">市价</option><option value="limit">限价</option></select></label>
      {draft.order_type === 'limit' ? <label className={styles.field}>限价<input aria-label="限价" value={draft.limit_price ?? ''} onChange={(e) => update('limit_price', e.target.value || null)} /></label> : null}
    </div> : null}
    {preview ? <div className={styles.meta}>预览：{JSON.stringify(preview)}</div> : null}
    {error ? <div className={styles.error} role="alert">{error}</div> : null}
    {status ? <div className={styles.meta}>订单状态：{status}</div> : null}
    <div className={styles.actions}>
      {isOrder && <button type="button" onClick={recalc} disabled={!dirty || busy}>重新计算</button>}
      <button type="button" className={styles.primary} onClick={confirm} disabled={dirty || busy}>{busy ? '处理中…' : `确认${isOrder ? (draft.side === 'buy' ? '模拟买入' : '模拟卖出') : payload.approval_type === 'paper_cancel' ? '取消模拟订单' : '重置模拟账户'}`}</button>
    </div>
  </div>
}
