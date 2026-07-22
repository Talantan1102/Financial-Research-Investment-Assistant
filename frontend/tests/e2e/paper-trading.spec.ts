import { expect, test } from '@playwright/test'

const API_HOST = 'http://localhost:8001'
const account = { id: 'account-1', generation: 1, initial_cash: '1000000.00', available_cash: '998000.00', frozen_cash: '2000.00', status: 'active' }
const holding = { generation: 1, ts_code: '600000.SH', name: '浦发银行', quantity: 200, frozen_quantity: 100, sellable_quantity: 100, average_cost: '10.0000' }

async function seedAuth(context: import('@playwright/test').BrowserContext) {
  await context.addInitScript(() => {
    window.localStorage.setItem('auth', JSON.stringify({ token: 'e2e-token', user: { id: 'u-e2e', username: 'e2e', email: 'e2e@example.com', is_active: true }, isLoggedIn: true }))
    window.localStorage.setItem('memory_onboarding_seen_v1', '1')
  })
}

async function stubPaperTrading(page: import('@playwright/test').Page) {
  await page.route(`${API_HOST}/api/v0/paper-trading/**`, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/account/reset-preview')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ account_id: account.id, generation: 1, current_initial_cash: account.initial_cash, replacement_initial_cash: '500000.00' }) })
      return
    }
    const body = url.pathname.endsWith('/account') ? account
      : url.pathname.endsWith('/holdings') ? [holding]
        : []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test.describe('paper trading account', () => {
  test('shows balances and separates total from sellable holdings', async ({ page, context }) => {
    await seedAuth(context); await stubPaperTrading(page)
    await page.goto('/paper-trading')
    await expect(page.getByText('模拟账户')).toBeVisible()
    await expect(page.getByText('可用资金')).toBeVisible()
    await expect(page.getByText('可卖 100')).toBeVisible()
    await expect(page.getByText('200', { exact: true })).toBeVisible()
  })

  test('reset opens preview first and renders a confirmation card', async ({ page, context }) => {
    await seedAuth(context); await stubPaperTrading(page)
    await page.goto('/paper-trading')
    await page.getByRole('button', { name: '重置账户' }).click()
    await expect(page.getByText('请先预览')).toBeVisible()
    await page.getByRole('button', { name: '生成确认卡' }).click()
    await expect(page.getByTestId('paper-approval-card')).toBeVisible()
    await expect(page.getByRole('button', { name: /确认重置模拟账户/ })).toBeVisible()
  })
})
