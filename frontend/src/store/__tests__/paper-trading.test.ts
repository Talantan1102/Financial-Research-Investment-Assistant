import { beforeEach, describe, expect, it } from 'vitest'
import { paperTradingActions, paperTradingState } from '@/store/paper-trading'
import type { ApprovalPayload } from '@/types/paper-trading'

const payload: ApprovalPayload = {
  approval_id: 'approval-a1', approval_type: 'paper_order', resource_id: 'o1',
  proposal: { side: 'buy', ts_code: '600519.SH', name: '贵州茅台', quantity: 100, order_type: 'market', limit_price: null },
  preview: { order_id: 'o1', draft: { side: 'buy', ts_code: '600519.SH', name: '贵州茅台', quantity: 100, order_type: 'market', limit_price: null }, quote: { price: '1500' }, estimated_gross: '150000', estimated_fees: {}, estimated_cash_required: '150100', available_cash: '500000', sellable_quantity: 0, market_phase: 'continuous', rules_version: 'v1' },
  expires_at: '2026-07-22T10:00:00Z',
}

describe('paper trading approval store', () => {
  beforeEach(() => paperTradingActions.reset())

  it('upserts by approval id without duplicating cards', () => {
    paperTradingActions.upsert(payload)
    paperTradingActions.upsert({ ...payload, proposal: { ...payload.proposal, quantity: 200 } })
    expect(Object.keys(paperTradingState.approvals)).toEqual(['approval-a1'])
    expect(paperTradingState.approvals['approval-a1'].proposal).toMatchObject({ quantity: 200 })
  })

  it('tracks preview, submitting and error phases', () => {
    paperTradingActions.upsert(payload)
    paperTradingActions.setSubmitting('approval-a1')
    expect(paperTradingState.approvals['approval-a1'].phase).toBe('submitting')
    paperTradingActions.setError('approval-a1', 'failed')
    expect(paperTradingState.approvals['approval-a1']).toMatchObject({ phase: 'error', error: 'failed' })
  })
})
