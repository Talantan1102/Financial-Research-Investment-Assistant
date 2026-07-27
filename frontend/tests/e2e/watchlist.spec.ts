import { expect, test, type BrowserContext, type Page, type Route } from '@playwright/test'

const USER = {
  id: 'watch-user',
  username: 'watch-user',
  email: 'watch@example.test',
  is_active: true,
  created_at: '2026-07-24T02:00:00Z',
}

async function seedAuthenticatedUser(context: BrowserContext) {
  await context.addInitScript(([key, value]: [string, string]) => {
    window.localStorage.setItem(key, value)
    window.localStorage.setItem('memory_onboarding_seen_v1', '1')
  }, ['auth', JSON.stringify({ token: 'watch-token', user: USER, isLoggedIn: true })])
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function installWatchlistBackend(page: Page) {
  let item:
    | {
        id: string
        ts_code: string
        name: string
        note: string | null
        monitoring_enabled: boolean
      }
    | undefined
  const mutations: string[] = []

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path === '/api/v1/tenants') {
      return json(route, [
        { id: 'tenant-watch', name: '个人空间', is_personal: true, role: 'owner' },
      ])
    }
    if (path === '/api/v1/tenants/tenant-watch/sessions') {
      return json(route, [])
    }
    if (path === '/api/v0/watchlist' && request.method() === 'GET') {
      return json(route, item ? [item] : [])
    }
    if (path === '/api/v0/watchlist' && request.method() === 'POST') {
      const body = request.postDataJSON() as {
        ts_code: string
        name: string
        monitoring_enabled?: boolean
      }
      item = {
        id: 'watch-item',
        ts_code: body.ts_code,
        name: body.name,
        note: null,
        monitoring_enabled: body.monitoring_enabled ?? false,
      }
      mutations.push('POST')
      return json(route, item, 201)
    }
    if (
      path === '/api/v0/watchlist/600519.SH' &&
      request.method() === 'PATCH'
    ) {
      const body = request.postDataJSON() as {
        note?: string | null
        monitoring_enabled?: boolean
      }
      item = {
        ...(item ?? {
          id: 'watch-item',
          ts_code: '600519.SH',
          name: '贵州茅台',
          note: null,
          monitoring_enabled: false,
        }),
        ...body,
      }
      mutations.push('PATCH')
      return json(route, item)
    }
    if (
      path === '/api/v0/watchlist/600519.SH' &&
      request.method() === 'DELETE'
    ) {
      item = undefined
      mutations.push('DELETE')
      return json(route, { removed: true })
    }
    return json(route, {})
  })

  return { mutations }
}

test('watchlist create defaults monitoring off, edits directly, then deletes without approval', async ({
  page,
  context,
}) => {
  await seedAuthenticatedUser(context)
  const backend = await installWatchlistBackend(page)
  let dialogCount = 0
  page.on('dialog', async (dialog) => {
    dialogCount += 1
    await dialog.dismiss()
  })

  await page.goto('/watchlist', { timeout: 30_000 })
  await expect(page.getByText('还没有自选股。输入代码和名称即可加入。')).toBeVisible()
  await page.getByPlaceholder('600519.SH').fill('600519.SH')
  await page.getByPlaceholder('贵州茅台').fill('贵州茅台')
  await page.getByRole('button', { name: '加入自选' }).click()

  const item = page.getByRole('article')
  await expect(item).toContainText('600519.SH')
  await expect(item).toContainText('未监控')
  await item.getByRole('button', { name: '编辑 贵州茅台' }).click()
  await item.getByLabel('贵州茅台备注').fill('长期观察')
  await item.getByRole('switch', { name: '贵州茅台监控' }).click()
  await expect(item.getByRole('switch')).toHaveAttribute('aria-checked', 'true')
  await item.getByRole('button', { name: '保存 贵州茅台' }).click()

  await expect(item).toContainText('长期观察')
  await expect(item).toContainText('监控中')
  await item.getByRole('button', { name: '移除 贵州茅台' }).click()
  await expect(page.getByText('还没有自选股。输入代码和名称即可加入。')).toBeVisible()

  expect(backend.mutations).toEqual(['POST', 'PATCH', 'DELETE'])
  expect(dialogCount).toBe(0)
  await expect(page.getByRole('region', { name: /审批|确认/ })).toHaveCount(0)
})
