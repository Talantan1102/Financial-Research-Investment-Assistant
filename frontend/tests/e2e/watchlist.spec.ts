import { expect, test } from '@playwright/test'

test('watchlist CRUD is direct and monitoring switch is editable', async ({ page, context }) => {
  await context.addInitScript(() => { localStorage.setItem('auth', JSON.stringify({ token: 'e2e', user: { id: 'u', username: 'u', email: 'u@e', is_active: true }, isLoggedIn: true })); localStorage.setItem('memory_onboarding_seen_v1', '1') })
  let items = [{ id: '1', ts_code: '600000.SH', name: '浦发银行', note: null, monitoring_enabled: false }]
  await page.route('**/api/v0/watchlist', async (route) => {
    if (route.request().method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(items) })
    items.push({ id: '2', ts_code: '000001.SZ', name: '平安银行', note: null, monitoring_enabled: false }); return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(items[1]) })
  })
  await page.route('**/api/v0/watchlist/*', async (route) => {
    const code = route.request().url().split('/').pop()!
    const item = items.find((x) => x.ts_code === code)
    if (route.request().method() === 'PATCH') { const body = route.request().postDataJSON(); Object.assign(item!, body); return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(item) }) }
    items = items.filter((x) => x.ts_code !== code); return route.fulfill({ status: 204, body: '' })
  })
  await page.goto('/watchlist')
  await expect(page.getByRole('row').nth(1).getByRole('textbox').first()).toHaveValue('浦发银行')
  await page.getByRole('switch').click()
  await page.getByPlaceholder('股票代码').fill('000001.SZ'); await page.getByPlaceholder('股票名称').fill('平安银行'); await page.getByRole('button', { name: /添\s*加/ }).click()
  await expect(page.getByRole('row').nth(2).getByRole('textbox').first()).toHaveValue('平安银行')
  await page.getByRole('button', { name: /删\s*除/ }).last().click()
})
