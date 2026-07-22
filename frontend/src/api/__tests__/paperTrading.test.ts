import { describe, expect, it } from 'vitest'
import { HttpResponse, http } from 'msw'
import { confirmOrder, getAccount, previewCancel, previewOrder } from '@/api/paperTrading'
import type { OrderDraft } from '@/types/paper-trading'
import { server } from '@/test-utils/msw-server'

const API_BASE = ((import.meta.env.VITE_API_BASE as string) ?? '').replace(/\/$/, '')
const draft: OrderDraft = {
  side: 'buy', ts_code: '600519.SH', name: '贵州茅台', quantity: 200,
  order_type: 'limit', limit_price: '1500.0000',
}

describe('paper trading api', () => {
  it('gets the default account', async () => {
    server.use(http.get(`${API_BASE}/api/v0/paper-trading/account`, () =>
      HttpResponse.json({ id: 'a1', generation: 1, initial_cash: '100000.00', available_cash: '100000.00', frozen_cash: '0.00', status: 'active' })))
    expect((await getAccount()).id).toBe('a1')
  })

  it('previews edited draft and confirms with a stable request id', async () => {
    server.use(
      http.post(`${API_BASE}/api/v0/paper-trading/orders/o1/preview`, async ({ request }) => {
        const body = await request.json() as { draft: OrderDraft }
        expect(body.draft.quantity).toBe(200)
        return HttpResponse.json({ order_id: 'o1', draft: body.draft, quote: { price: '1500' }, estimated_gross: '300000', estimated_fees: {}, estimated_cash_required: '300000', available_cash: '500000', sellable_quantity: 0, market_phase: 'continuous', rules_version: 'v1' })
      }),
      http.post(`${API_BASE}/api/v0/paper-trading/orders/o1/confirm`, async ({ request }) => {
        const body = await request.json() as { client_request_id: string; draft: OrderDraft }
        expect(body.client_request_id).toBe('approval-a1')
        expect(body.draft.quantity).toBe(200)
        return HttpResponse.json({ id: 'o1', status: 'open' })
      }),
    )
    expect((await previewOrder('o1', draft)).draft.quantity).toBe(200)
    expect((await confirmOrder('o1', { client_request_id: 'approval-a1', draft })).id).toBe('o1')
  })

  it('previews cancellation without sending a request body', async () => {
    server.use(http.post(`${API_BASE}/api/v0/paper-trading/orders/o1/cancel-preview`, async ({ request }) => {
      expect(await request.text()).toBe('')
      return HttpResponse.json({ order_id: 'o1', status: 'open', filled_quantity: 0, remaining_quantity: 100, reserved_cash: '0.00', reserved_quantity: 0 })
    }))
    expect((await previewCancel('o1')).remaining_quantity).toBe(100)
  })
})
