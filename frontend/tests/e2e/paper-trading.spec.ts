import { expect, test, type BrowserContext, type Page, type Route } from '@playwright/test'
import { isDeepStrictEqual } from 'node:util'

const USER = {
  id: 'paper-user',
  username: 'paper-user',
  email: 'paper@example.test',
  is_active: true,
  created_at: '2026-07-24T01:00:00Z',
}
const TENANT_ID = 'tenant-paper'
const SESSION_ID = 'session-paper'
const RUN_ID = 'run-paper'
const ORDER_ID = '11111111-1111-4111-8111-111111111111'
const EDITED_DRAFT = {
  side: 'buy',
  ts_code: '600519.SH',
  name: '贵州茅台',
  quantity: 100,
  order_type: 'limit',
  limit_price: '1500.00',
}

async function seedAuthenticatedUser(context: BrowserContext) {
  await context.addInitScript(([key, value]: [string, string]) => {
    window.localStorage.setItem(key, value)
    window.localStorage.setItem('memory_onboarding_seen_v1', '1')
  }, ['auth', JSON.stringify({ token: 'paper-token', user: USER, isLoggedIn: true })])
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function installPaperBackend(page: Page) {
  let runPhase: 'new' | 'waiting' | 'completed' = 'new'
  let orderCreated = false
  let approvedArguments: Record<string, unknown> | null = null
  let previewedArguments: Record<string, unknown> | null = null
  const requestedPrompts: string[] = []
  const unexpectedRequests: string[] = []

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    if (!path.startsWith('/api/')) return route.continue()

    if (path === '/api/v1/tenants' && request.method() === 'GET') {
      return json(route, [
        { id: TENANT_ID, name: '个人空间', is_personal: true, role: 'owner' },
      ])
    }
    if (
      path === `/api/v1/tenants/${TENANT_ID}/sessions` &&
      request.method() === 'GET'
    ) {
      return json(route, [])
    }
    if (
      path === `/api/v1/tenants/${TENANT_ID}/runs` &&
      request.method() === 'POST'
    ) {
      const body = request.postDataJSON() as { prompt: string }
      requestedPrompts.push(body.prompt)
      runPhase = 'waiting'
      return json(route, {
        id: RUN_ID,
        tenant_id: TENANT_ID,
        session_id: SESSION_ID,
        created_by_user_id: USER.id,
        run_type: 'chat',
        status: 'running',
        replaces_run_id: null,
        retry_count: 0,
        created_at: '2026-07-24T01:01:00Z',
        queued_at: '2026-07-24T01:01:00Z',
        finished_at: null,
        error_code: null,
        error_message: null,
      })
    }
    if (
      path === `/api/v1/tenants/${TENANT_ID}/runs/${RUN_ID}/events` &&
      request.method() === 'GET'
    ) {
      const body =
        runPhase === 'waiting'
          ? [
              'id: approval-1',
              'event: approval_request',
              `data: ${JSON.stringify({
                tool_calls: [
                  {
                    id: 'call-buy',
                    name: 'place_paper_order',
                    arguments: {
                      side: 'buy',
                      ts_code: '600519.SH',
                      name: '贵州茅台',
                      quantity: 100,
                      order_type: 'limit',
                      limit_price: '1450.00',
                    },
                  },
                ],
                editable_tool_call_ids: ['call-buy'],
              })}`,
              '',
              'id: paused-1',
              'event: run.paused',
              `data: ${JSON.stringify({
                pause_type: 'approval',
                request: {
                  tool_calls: [
                    {
                      id: 'call-buy',
                      name: 'place_paper_order',
                      arguments: {
                        side: 'buy',
                        ts_code: '600519.SH',
                        name: '贵州茅台',
                        quantity: 100,
                        order_type: 'limit',
                        limit_price: '1450.00',
                      },
                    },
                  ],
                  editable_tool_call_ids: ['call-buy'],
                },
              })}`,
              '',
              '',
            ].join('\n')
          : [
              'id: completed-1',
              'event: run.completed',
              `data: ${JSON.stringify({ content: '模拟买入已提交。' })}`,
              '',
              '',
            ].join('\n')
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body,
      })
    }
    if (
      path === `/api/v1/tenants/${TENANT_ID}/runs/${RUN_ID}/resume` &&
      request.method() === 'POST'
    ) {
      const body = request.postDataJSON() as {
        response: {
          approved: boolean
          edited_arguments: Record<string, Record<string, unknown>>
        }
      }
      const editedArguments = body.response.edited_arguments?.['call-buy']
      if (
        body.response.approved &&
        (previewedArguments === null ||
          !isDeepStrictEqual(editedArguments, previewedArguments))
      ) {
        unexpectedRequests.push(
          `invalid approved resume: ${JSON.stringify(body)}`,
        )
        return json(route, { detail: 'approved arguments were not previewed' }, 409)
      }
      approvedArguments = editedArguments ?? null
      orderCreated = body.response.approved
      runPhase = 'completed'
      return json(route, {
        id: RUN_ID,
        tenant_id: TENANT_ID,
        session_id: SESSION_ID,
        created_by_user_id: USER.id,
        run_type: 'chat',
        status: 'running',
        replaces_run_id: null,
        retry_count: 0,
        created_at: '2026-07-24T01:01:00Z',
        queued_at: '2026-07-24T01:01:00Z',
        finished_at: null,
        error_code: null,
        error_message: null,
      })
    }
    if (
      path === `/api/v1/tenants/${TENANT_ID}/runs/${RUN_ID}` &&
      request.method() === 'GET'
    ) {
      return json(route, {
        id: RUN_ID,
        tenant_id: TENANT_ID,
        session_id: SESSION_ID,
        created_by_user_id: USER.id,
        run_type: 'chat',
        status: runPhase === 'completed' ? 'completed' : 'waiting_approval',
        replaces_run_id: null,
        retry_count: 0,
        created_at: '2026-07-24T01:01:00Z',
        queued_at: '2026-07-24T01:01:00Z',
        finished_at:
          runPhase === 'completed' ? '2026-07-24T01:02:00Z' : null,
        error_code: null,
        error_message: null,
      })
    }
    if (
      path === `/api/v1/tenants/${TENANT_ID}/sessions/${SESSION_ID}` &&
      request.method() === 'GET'
    ) {
      return json(route, {
        id: SESSION_ID,
        tenant_id: TENANT_ID,
        created_by_user_id: USER.id,
        title: '模拟买入贵州茅台',
        created_at: '2026-07-24T01:01:00Z',
        updated_at: '2026-07-24T01:02:00Z',
        archived_at: null,
        messages: orderCreated
          ? [
              {
                id: 'message-result',
                role: 'assistant',
                content: '模拟买入已提交。',
                status: 'done',
                created_at: '2026-07-24T01:02:00Z',
              },
            ]
          : [],
        has_more: false,
        active_run_id: runPhase === 'waiting' ? RUN_ID : null,
        active_run_status:
          runPhase === 'waiting' ? 'waiting_approval' : null,
        active_pause_type: runPhase === 'waiting' ? 'approval' : null,
        active_pause_request:
          runPhase === 'waiting'
            ? {
                tool_calls: [
                  {
                    id: 'call-buy',
                    name: 'place_paper_order',
                    arguments: {
                      side: 'buy',
                      ts_code: '600519.SH',
                      name: '贵州茅台',
                      quantity: 100,
                      order_type: 'limit',
                      limit_price: '1450.00',
                    },
                  },
                ],
                editable_tool_call_ids: ['call-buy'],
              }
            : null,
        revisions: [],
        revisions_has_more: false,
        revisions_next_cursor: null,
        latest_run_id: RUN_ID,
      })
    }
    if (
      path === '/api/v0/paper-trading/orders/preview' &&
      request.method() === 'POST'
    ) {
      const body = request.postDataJSON() as {
        draft: Record<string, unknown>
      }
      if (!isDeepStrictEqual(body, { draft: EDITED_DRAFT })) {
        unexpectedRequests.push(`invalid preview: ${JSON.stringify(body)}`)
        return json(route, { detail: 'preview draft mismatch' }, 422)
      }
      previewedArguments = JSON.parse(
        JSON.stringify(body.draft),
      ) as Record<string, unknown>
      return json(route, {
        draft: previewedArguments,
        quote: {
          ts_code: '600519.SH',
          name: '贵州茅台',
          last_price: '1498.00',
          source: 'e2e-fixture',
        },
        estimated_gross: '150000.00',
        estimated_fees: {
          commission: '45.00',
          stamp_duty: '0.00',
          transfer_fee: '1.50',
          total: '46.50',
        },
        estimated_cash_required: '150046.50',
        available_cash: '1000000.00',
        sellable_quantity: 0,
        market_phase: 'continuous',
        rules_version: 'cn-a-share-v1',
      })
    }
    if (
      path === '/api/v0/paper-trading/account' &&
      request.method() === 'GET'
    ) {
      return json(route, {
        id: 'account-paper',
        generation: 1,
        initial_cash: '1000000.00',
        available_cash: orderCreated ? '849953.50' : '1000000.00',
        frozen_cash: '0.00',
        status: 'active',
      })
    }
    if (
      path === '/api/v0/paper-trading/holdings' &&
      request.method() === 'GET'
    ) {
      return json(route, [])
    }
    if (
      path === '/api/v0/paper-trading/orders' &&
      request.method() === 'GET'
    ) {
      return json(
        route,
        orderCreated
          ? [
              {
                id: ORDER_ID,
                account_generation: 1,
                ts_code: '600519.SH',
                name: '贵州茅台',
                side: 'buy',
                order_type: 'limit',
                quantity: 100,
                limit_price: String(approvedArguments?.limit_price ?? ''),
                filled_quantity: 100,
                avg_fill_price: '1500.00',
                reserved_cash: '0.00',
                reserved_quantity: 0,
                status: 'filled',
                created_at: '2026-07-24T01:01:00Z',
                confirmed_at: '2026-07-24T01:01:30Z',
                completed_at: '2026-07-24T01:02:00Z',
              },
            ]
          : [],
      )
    }
    unexpectedRequests.push(`${request.method()} ${path}`)
    return json(route, { detail: `unexpected API route: ${path}` }, 500)
  })

  return {
    requestedPrompts,
    approvedArguments: () => approvedArguments,
    previewedArguments: () => previewedArguments,
    unexpectedRequests,
  }
}

test('buy instruction pauses for editable preview, resumes, and appears in the same account', async ({
  page,
  context,
}) => {
  await seedAuthenticatedUser(context)
  const backend = await installPaperBackend(page)

  await page.goto('/chat', { timeout: 30_000 })
  const input = page.getByTestId('input-textarea')
  await expect(input).toBeEnabled()
  await input.fill('给我买入100股贵州茅台')
  await page.getByRole('button', { name: '发送' }).click()

  const approval = page.getByRole('region', { name: '模拟交易审批' })
  await expect(approval).toBeVisible()
  await expect(approval.getByText('模拟买入审批')).toBeVisible()
  expect(backend.requestedPrompts).toEqual(['给我买入100股贵州茅台'])

  await approval.getByLabel('限价').fill('1500.00')
  await approval.getByRole('button', { name: /预览/ }).click()
  await expect(approval.getByText('预览有效')).toBeVisible()
  await expect(approval.getByText('¥150,046.50')).toBeVisible()
  await approval.getByRole('button', { name: '确认买入' }).click()

  await expect(approval).toBeHidden()
  await expect(page.getByText('模拟买入已提交。')).toBeVisible()
  expect(backend.approvedArguments()).toMatchObject({
    side: 'buy',
    ts_code: '600519.SH',
    quantity: 100,
    order_type: 'limit',
    limit_price: '1500.00',
  })
  expect(backend.previewedArguments()).toEqual(EDITED_DRAFT)

  await page.goto('/paper-trading')
  await expect(page.getByRole('heading', { name: '模拟账户' })).toBeVisible()
  await expect(page.getByLabel('资金概览')).toContainText('849,953.50')
  const orderRow = page.getByRole('row').filter({ hasText: '600519.SH' })
  await expect(orderRow).toContainText('贵州茅台')
  await expect(orderRow).toContainText('买入')
  await expect(orderRow).toContainText('1,500.0000')
  await expect(orderRow).toContainText('已成交')
  expect(backend.unexpectedRequests).toEqual([])
})

test('read-only paper backend routes fail closed on wrong HTTP methods', async ({
  page,
}) => {
  const backend = await installPaperBackend(page)
  await page.goto('/login', { timeout: 30_000 })
  const wrongRequests = [
    { path: '/api/v1/tenants', method: 'POST' },
    {
      path: `/api/v1/tenants/${TENANT_ID}/sessions`,
      method: 'DELETE',
    },
    {
      path: `/api/v1/tenants/${TENANT_ID}/runs/${RUN_ID}/events`,
      method: 'POST',
    },
    {
      path: `/api/v1/tenants/${TENANT_ID}/sessions/${SESSION_ID}`,
      method: 'DELETE',
    },
    { path: '/api/v0/paper-trading/account', method: 'POST' },
    { path: '/api/v0/paper-trading/holdings', method: 'DELETE' },
    { path: '/api/v0/paper-trading/orders', method: 'DELETE' },
  ]

  const statuses = await page.evaluate(async (requests) => {
    return Promise.all(
      requests.map(async ({ path, method }) => {
        const response = await fetch(path, { method })
        return response.status
      }),
    )
  }, wrongRequests)

  expect(statuses).toEqual(wrongRequests.map(() => 500))
  expect(backend.unexpectedRequests).toEqual(
    wrongRequests.map(({ path, method }) => `${method} ${path}`),
  )
})
