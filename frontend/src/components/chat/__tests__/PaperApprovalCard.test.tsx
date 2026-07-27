import { previewPaperOrder } from '@/api/paperTrading'
import { PaperApprovalCard } from '@/components/chat/PaperApprovalCard'
import { renderWithProviders } from '@/test-utils/render'
import { act, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/paperTrading', () => ({
  previewPaperOrder: vi.fn(),
}))

const request = {
  tool_calls: [
    {
      id: 'trade-1',
      name: 'place_paper_order',
      arguments: JSON.stringify({
        side: 'buy',
        ts_code: '600519.SH',
        name: '贵州茅台',
        quantity: 100,
        order_type: 'limit',
        limit_price: '1500.0000',
      }),
    },
  ],
  editable_tool_call_ids: ['trade-1'],
}

const preview = {
  draft: {
    side: 'buy' as const,
    ts_code: '600519.SH',
    name: '贵州茅台',
    quantity: 200,
    order_type: 'limit' as const,
    limit_price: '1498.5000',
  },
  quote: {
    ts_code: '600519.SH',
    name: '贵州茅台',
    price: '1498.5000',
    timestamp: '2026-07-23T02:00:00Z',
    source: 'test',
    is_suspended: false,
    bid1: '1498.4000',
    ask1: '1498.5000',
    upper_limit: '1648.3000',
    lower_limit: '1348.7000',
  },
  estimated_gross: '299700.00',
  estimated_fees: {
    commission: '89.91',
    stamp_duty: '0.00',
    transfer_fee: '3.00',
    total: '92.91',
  },
  estimated_cash_required: '299792.91',
  available_cash: '1000000.00',
  sellable_quantity: 0,
  market_phase: 'continuous',
  rules_version: 'cn-a-v1',
}

function nextRequest(callId: string, quantity: number) {
  return {
    ...request,
    tool_calls: [
      {
        ...request.tool_calls[0],
        id: callId,
        arguments: JSON.stringify({
          ...JSON.parse(request.tool_calls[0].arguments),
          quantity,
        }),
      },
    ],
    editable_tool_call_ids: [callId],
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, reject, resolve }
}

describe('<PaperApprovalCard>', () => {
  beforeEach(() => {
    vi.mocked(previewPaperOrder).mockReset()
  })

  it('shows the proposed stock identity as editable order fields', () => {
    renderWithProviders(
      <PaperApprovalCard request={request} onResume={vi.fn()} />,
    )

    expect(screen.getByRole('textbox', { name: '股票代码' })).toHaveValue(
      '600519.SH',
    )
    expect(screen.getByRole('textbox', { name: '股票名称' })).toHaveValue(
      '贵州茅台',
    )
  })

  it('invalidates the old preview after edits and approves only the newly previewed draft', async () => {
    const user = userEvent.setup()
    const onResume = vi.fn(async () => ({ ok: true as const }))
    vi.mocked(previewPaperOrder).mockResolvedValue({
      ...preview,
      draft: {
        ...preview.draft,
        ts_code: '000001.SZ',
        name: '平安银行',
      },
      quote: {
        ...preview.quote,
        ts_code: '000001.SZ',
        name: '平安银行',
      },
    })
    renderWithProviders(
      <PaperApprovalCard request={request} onResume={onResume} />,
    )

    expect(screen.getByRole('button', { name: '确认买入' })).toBeDisabled()
    await user.clear(screen.getByRole('textbox', { name: '股票代码' }))
    await user.type(
      screen.getByRole('textbox', { name: '股票代码' }),
      '000001.SZ',
    )
    await user.clear(screen.getByRole('textbox', { name: '股票名称' }))
    await user.type(
      screen.getByRole('textbox', { name: '股票名称' }),
      '平安银行',
    )
    await user.clear(screen.getByLabelText('数量'))
    await user.type(screen.getByLabelText('数量'), '200')
    await user.clear(screen.getByLabelText('限价'))
    await user.type(screen.getByLabelText('限价'), '1498.5')
    expect(screen.getByText('参数已修改，请重新预览')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认买入' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: '重新预览' }))
    expect(previewPaperOrder).toHaveBeenCalledWith(
      {
        draft: expect.objectContaining({
          ts_code: '000001.SZ',
          name: '平安银行',
          quantity: 200,
          limit_price: '1498.5',
        }),
      },
      { signal: expect.any(AbortSignal) },
    )
    expect(await screen.findByText('¥299,792.91')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '确认买入' }))
    expect(onResume).toHaveBeenCalledWith({
      approved: true,
      edited_arguments: {
        'trade-1': {
          side: 'buy',
          ts_code: '000001.SZ',
          name: '平安银行',
          quantity: 200,
          order_type: 'limit',
          limit_price: '1498.5000',
        },
      },
    })
  })

  it('rejects through Run resume without calling the preview endpoint', async () => {
    const user = userEvent.setup()
    const onResume = vi.fn(async () => ({ ok: true as const }))
    renderWithProviders(
      <PaperApprovalCard request={request} onResume={onResume} />,
    )
    await user.click(screen.getByRole('button', { name: '拒绝交易' }))
    expect(previewPaperOrder).not.toHaveBeenCalled()
    expect(onResume).toHaveBeenCalledWith({ approved: false })
  })

  it('accepts only the latest preview after rapid stock identity edits', async () => {
    const user = userEvent.setup()
    let resolveFirst!: (value: typeof preview) => void
    vi.mocked(previewPaperOrder)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve
          }),
      )
      .mockResolvedValueOnce({
        ...preview,
        estimated_cash_required: '449639.36',
        draft: {
          ...preview.draft,
          ts_code: '000001.SZ',
          name: '平安银行',
        },
      })
    renderWithProviders(
      <PaperApprovalCard request={request} onResume={vi.fn()} />,
    )

    await user.click(screen.getByRole('button', { name: '预览交易' }))
    await user.clear(screen.getByRole('textbox', { name: '股票代码' }))
    await user.type(
      screen.getByRole('textbox', { name: '股票代码' }),
      '000001.SZ',
    )
    await user.clear(screen.getByRole('textbox', { name: '股票名称' }))
    await user.type(
      screen.getByRole('textbox', { name: '股票名称' }),
      '平安银行',
    )
    await user.click(screen.getByRole('button', { name: '重新预览' }))
    expect(previewPaperOrder).toHaveBeenLastCalledWith(
      {
        draft: expect.objectContaining({
          ts_code: '000001.SZ',
          name: '平安银行',
        }),
      },
      { signal: expect.any(AbortSignal) },
    )
    expect(await screen.findByText('¥449,639.36')).toBeInTheDocument()
    act(() => resolveFirst(preview))
    expect(screen.queryByText('¥299,792.91')).not.toBeInTheDocument()
  })

  it('shows stock identity validation inline and keeps preview and approval closed', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <PaperApprovalCard request={request} onResume={vi.fn()} />,
    )

    const code = screen.getByRole('textbox', { name: '股票代码' })
    const name = screen.getByRole('textbox', { name: '股票名称' })
    await user.clear(code)
    await user.type(code, '   ')
    await user.clear(name)

    expect(screen.getByText('股票代码不能为空')).toBeInTheDocument()
    expect(screen.getByText('股票名称不能为空')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新预览' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '确认买入' })).toBeDisabled()
    expect(previewPaperOrder).not.toHaveBeenCalled()
  })

  it('keeps stock validation descriptions unique across approval cards', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <>
        <PaperApprovalCard request={request} onResume={vi.fn()} />
        <PaperApprovalCard request={request} onResume={vi.fn()} />
      </>,
    )

    const codeInputs = screen.getAllByRole('textbox', { name: '股票代码' })
    await user.clear(codeInputs[0])
    await user.clear(codeInputs[1])

    const descriptionIds = codeInputs.map((input) =>
      input.getAttribute('aria-describedby'),
    )
    expect(descriptionIds[0]).toBeTruthy()
    expect(descriptionIds[1]).toBeTruthy()
    expect(descriptionIds[0]).not.toBe(descriptionIds[1])
    for (const id of descriptionIds) {
      expect(document.getElementById(id!)).toHaveTextContent('股票代码不能为空')
    }
  })

  it('keeps approval disabled after a stock preview failure', async () => {
    const user = userEvent.setup()
    vi.mocked(previewPaperOrder).mockRejectedValue(
      new Error('没有找到该股票行情'),
    )
    renderWithProviders(
      <PaperApprovalCard request={request} onResume={vi.fn()} />,
    )

    await user.clear(screen.getByRole('textbox', { name: '股票代码' }))
    await user.type(
      screen.getByRole('textbox', { name: '股票代码' }),
      '000001.SZ',
    )
    await user.click(screen.getByRole('button', { name: '重新预览' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '没有找到该股票行情',
    )
    expect(screen.getByRole('button', { name: '确认买入' })).toBeDisabled()
  })

  it('aborts the previous preview and treats AbortError as silent control flow', async () => {
    const user = userEvent.setup()
    let firstSignal: AbortSignal | undefined
    vi.mocked(previewPaperOrder)
      .mockImplementationOnce((_payload, options) => {
        firstSignal = options?.signal
        return new Promise((_resolve, reject) => {
          firstSignal?.addEventListener(
            'abort',
            () => reject(new DOMException('Aborted', 'AbortError')),
            { once: true },
          )
        })
      })
      .mockResolvedValueOnce(preview)
    renderWithProviders(
      <PaperApprovalCard request={request} onResume={vi.fn()} />,
    )

    await user.click(screen.getByRole('button', { name: '预览交易' }))
    expect(firstSignal).toBeInstanceOf(AbortSignal)
    await user.click(screen.getByRole('button', { name: '预览交易' }))

    expect(firstSignal?.aborted).toBe(true)
    expect(await screen.findByText('¥299,792.91')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('aborts an in-flight preview when the pause identity changes', async () => {
    const user = userEvent.setup()
    let signal: AbortSignal | undefined
    vi.mocked(previewPaperOrder).mockImplementationOnce((_payload, options) => {
      signal = options?.signal
      return new Promise(() => {})
    })
    const rendered = renderWithProviders(
      <PaperApprovalCard request={request} onResume={vi.fn()} />,
    )

    await user.click(screen.getByRole('button', { name: '预览交易' }))
    rendered.rerender(
      <PaperApprovalCard
        request={nextRequest('trade-replacement', 200)}
        onResume={vi.fn()}
      />,
    )

    expect(signal?.aborted).toBe(true)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '预览交易' })).toBeEnabled()
  })

  it('aborts an in-flight preview when the card unmounts', async () => {
    const user = userEvent.setup()
    let signal: AbortSignal | undefined
    vi.mocked(previewPaperOrder).mockImplementationOnce((_payload, options) => {
      signal = options?.signal
      return new Promise(() => {})
    })
    const rendered = renderWithProviders(
      <PaperApprovalCard request={request} onResume={vi.fn()} />,
    )

    await user.click(screen.getByRole('button', { name: '预览交易' }))
    rendered.unmount()

    expect(signal?.aborted).toBe(true)
  })

  it('fences an in-flight preview when a restored pause replaces the card', async () => {
    const user = userEvent.setup()
    let resolveOld!: (value: typeof preview) => void
    vi.mocked(previewPaperOrder).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve
        }),
    )
    const rendered = renderWithProviders(
      <PaperApprovalCard request={request} onResume={vi.fn()} />,
    )
    await user.click(screen.getByRole('button', { name: '预览交易' }))

    rendered.rerender(
      <PaperApprovalCard
        request={{
          ...request,
          tool_calls: [
            {
              ...request.tool_calls[0],
              arguments: JSON.stringify({
                ...JSON.parse(request.tool_calls[0].arguments),
                quantity: 200,
              }),
            },
          ],
        }}
        onResume={vi.fn()}
      />,
    )
    expect(screen.getByText('批准前请先预览')).toBeInTheDocument()
    act(() => resolveOld(preview))
    expect(screen.queryByText('¥299,792.91')).not.toBeInTheDocument()
  })

  it('lets a replacement pause submit immediately and ignores the old resolved result', async () => {
    const user = userEvent.setup()
    const oldResume = deferred<{ ok: boolean; error?: string }>()
    const newResume = deferred<{ ok: boolean; error?: string }>()
    const oldHandler = vi.fn(() => oldResume.promise)
    const newHandler = vi.fn(() => newResume.promise)
    vi.mocked(previewPaperOrder).mockResolvedValue(preview)
    const rendered = renderWithProviders(
      <PaperApprovalCard request={request} onResume={oldHandler} />,
    )

    await user.click(screen.getByRole('button', { name: '预览交易' }))
    await user.click(await screen.findByRole('button', { name: '确认买入' }))
    expect(oldHandler).toHaveBeenCalledTimes(1)

    rendered.rerender(
      <PaperApprovalCard
        request={nextRequest('trade-2', 200)}
        onResume={newHandler}
      />,
    )
    expect(screen.getByRole('button', { name: '预览交易' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: '预览交易' }))
    await user.click(await screen.findByRole('button', { name: '确认买入' }))
    expect(newHandler).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: '提交中…' })).toBeDisabled()

    await act(async () => {
      oldResume.resolve({ ok: false, error: '旧审批失败' })
      await Promise.resolve()
    })
    expect(screen.queryByText('旧审批失败')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '提交中…' })).toBeDisabled()

    await act(async () => {
      newResume.resolve({ ok: true })
      await Promise.resolve()
    })
  })

  it('keeps a replacement pause isolated when the old resume rejects', async () => {
    const user = userEvent.setup()
    const oldResume = deferred<{ ok: boolean; error?: string }>()
    const newResume = deferred<{ ok: boolean; error?: string }>()
    const oldHandler = vi.fn(() => oldResume.promise)
    const newHandler = vi.fn(() => newResume.promise)
    vi.mocked(previewPaperOrder).mockResolvedValue(preview)
    const rendered = renderWithProviders(
      <PaperApprovalCard request={request} onResume={oldHandler} />,
    )

    await user.click(screen.getByRole('button', { name: '预览交易' }))
    await user.click(await screen.findByRole('button', { name: '确认买入' }))
    rendered.rerender(
      <PaperApprovalCard
        request={nextRequest('trade-3', 300)}
        onResume={newHandler}
      />,
    )
    expect(screen.getByRole('button', { name: '预览交易' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: '预览交易' }))
    await user.click(await screen.findByRole('button', { name: '确认买入' }))
    expect(newHandler).toHaveBeenCalledTimes(1)

    await act(async () => {
      oldResume.reject(new Error('旧请求异常'))
      await Promise.resolve()
    })
    expect(screen.queryByText('旧请求异常')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '提交中…' })).toBeDisabled()

    await act(async () => {
      newResume.resolve({ ok: true })
      await Promise.resolve()
    })
  })

  it('fails closed for malformed tool arguments', () => {
    renderWithProviders(
      <PaperApprovalCard
        request={{
          tool_calls: [
            { id: 'trade-1', name: 'place_paper_order', arguments: '{bad' },
          ],
          editable_tool_call_ids: ['trade-1'],
        }}
        onResume={vi.fn()}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('交易参数无法读取')
    expect(
      screen.queryByRole('button', { name: '确认买入' }),
    ).not.toBeInTheDocument()
  })

  it('fences repeated rejection clicks when malformed arguments are shown', async () => {
    const user = userEvent.setup()
    const onResume = vi.fn(() => new Promise<{ ok: boolean }>(() => {}))
    renderWithProviders(
      <PaperApprovalCard
        request={{
          tool_calls: [
            { id: 'trade-1', name: 'place_paper_order', arguments: '{bad' },
          ],
          editable_tool_call_ids: ['trade-1'],
        }}
        onResume={onResume}
      />,
    )
    const reject = screen.getByRole('button', { name: '拒绝交易' })
    await user.dblClick(reject)
    expect(onResume).toHaveBeenCalledTimes(1)
    expect(reject).toBeDisabled()
  })

  it('keeps an edited account reset disabled until the money value is valid', async () => {
    const user = userEvent.setup()
    const onResume = vi.fn(async () => ({ ok: true as const }))
    renderWithProviders(
      <PaperApprovalCard
        request={{
          tool_calls: [
            {
              id: 'reset-1',
              name: 'reset_paper_account',
              arguments: { initial_cash: '1000000.00' },
            },
          ],
          editable_tool_call_ids: ['reset-1'],
        }}
        onResume={onResume}
      />,
    )
    const input = screen.getByLabelText('重置后的初始资金')
    await user.clear(input)
    expect(screen.getByRole('button', { name: '确认重置' })).toBeDisabled()
    await user.type(input, '800000.00')
    await user.click(screen.getByRole('button', { name: '确认重置' }))
    expect(onResume).toHaveBeenCalledWith({
      approved: true,
      edited_arguments: { 'reset-1': { initial_cash: '800000.00' } },
    })
  })

  it('does not show stock identity fields on reset or cancel cards', () => {
    const rendered = renderWithProviders(
      <PaperApprovalCard
        request={{
          tool_calls: [
            {
              id: 'reset-1',
              name: 'reset_paper_account',
              arguments: { initial_cash: '1000000.00' },
            },
          ],
          editable_tool_call_ids: ['reset-1'],
        }}
        onResume={vi.fn()}
      />,
    )
    expect(
      screen.queryByRole('textbox', { name: '股票代码' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('textbox', { name: '股票名称' }),
    ).not.toBeInTheDocument()

    rendered.rerender(
      <PaperApprovalCard
        request={{
          tool_calls: [
            {
              id: 'cancel-1',
              name: 'cancel_paper_order',
              arguments: {
                order_id: '11111111-1111-4111-8111-111111111111',
              },
            },
          ],
          editable_tool_call_ids: ['cancel-1'],
        }}
        onResume={vi.fn()}
      />,
    )
    expect(
      screen.queryByRole('textbox', { name: '股票代码' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('textbox', { name: '股票名称' }),
    ).not.toBeInTheDocument()
  })
})
