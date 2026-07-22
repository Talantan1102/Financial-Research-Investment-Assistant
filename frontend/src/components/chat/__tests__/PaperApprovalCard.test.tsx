import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PaperApprovalCard } from '@/components/chat/PaperApprovalCard'
import type { ChatMessage } from '@/types/chat'

const api = vi.hoisted(() => ({ previewOrder: vi.fn(), confirmOrder: vi.fn(), getOrder: vi.fn(), confirmCancel: vi.fn(), confirmReset: vi.fn() }))
vi.mock('@/api/paperTrading', () => api)
const message = (over: Record<string, unknown> = {}): ChatMessage => ({
  id: 'm1', session_id: 's1', role: 'assistant', content: '', message_type: 'paper_approval', research_report_id: null, research_report_summary: null, created_at: '2026-01-01',
  tool_call_data: { approval_id: 'a1', approval_type: 'paper_order', resource_id: 'o1', proposal: { side: 'buy', ts_code: '600000.SH', name: '浦发银行', quantity: 100, order_type: 'market', limit_price: null }, preview: { order_id: 'o1', draft: { side: 'buy', ts_code: '600000.SH', name: '浦发银行', quantity: 100, order_type: 'market', limit_price: null }, quote: { price: '10' }, estimated_gross: '1000', estimated_fees: {}, estimated_cash_required: '1000', available_cash: '10000', sellable_quantity: 0, market_phase: 'open', rules_version: 'v1' }, expires_at: '2026-01-02', ...over },
})
describe('PaperApprovalCard', () => {
  beforeEach(() => { vi.clearAllMocks(); api.previewOrder.mockResolvedValue({}); api.confirmOrder.mockResolvedValue({ id: 'o1', status: 'queued' }); api.getOrder.mockResolvedValue({ id: 'o1', status: 'filled' }) })
  it('repreviews edited quantity before confirming final draft', async () => {
    const user = userEvent.setup(); render(<PaperApprovalCard message={message()} />)
    await user.clear(screen.getByLabelText('数量')); await user.type(screen.getByLabelText('数量'), '200')
    expect(screen.getByRole('button', { name: '确认模拟买入' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '重新计算' }))
    expect(api.previewOrder).toHaveBeenCalledWith('o1', expect.objectContaining({ quantity: 200 }))
    await user.click(screen.getByRole('button', { name: '确认模拟买入' }))
    expect(api.confirmOrder).toHaveBeenCalledWith('o1', expect.objectContaining({ client_request_id: 'a1', draft: expect.objectContaining({ quantity: 200 }) }))
  })
  it('uses approval id for cancel confirmation', async () => {
    api.confirmCancel.mockResolvedValue({ id: 'o1', status: 'cancelled' })
    render(<PaperApprovalCard message={message({ approval_type: 'paper_cancel', proposal: {}, preview: { order_id: 'o1', status: 'open', filled_quantity: 0, remaining_quantity: 100, reserved_cash: '0', reserved_quantity: 0 } })} />)
    await userEvent.setup().click(screen.getByRole('button', { name: '确认取消模拟订单' }))
    expect(api.confirmCancel).toHaveBeenCalledWith('o1', { confirmation_id: 'a1' })
  })
})
