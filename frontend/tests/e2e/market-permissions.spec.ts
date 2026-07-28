import { expect, test, type BrowserContext, type Page, type Route } from '@playwright/test'

const USER = {
  id: 'permission-user',
  username: 'permission-user',
  email: 'permission@example.test',
  is_active: true,
  created_at: '2026-07-27T01:00:00Z',
}

const STAR_NOT_APPLIED = {
  entitlement_id: 'entitlement-star',
  market: 'star',
  status: 'not_applied',
  can_buy: false,
  can_sell: false,
  can_subscribe: false,
  rule_version: null,
  enabled_at: null,
  restricted_at: null,
}

const STAR_ENABLED = {
  ...STAR_NOT_APPLIED,
  status: 'enabled',
  can_buy: true,
  can_sell: true,
  can_subscribe: true,
  rule_version: 'star-access-2026-07',
  enabled_at: '2026-07-27T02:00:00Z',
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function seedAuthenticatedUser(context: BrowserContext) {
  await context.addInitScript(
    ([key, value]: [string, string]) => {
      window.localStorage.setItem(key, value)
      window.localStorage.setItem('memory_onboarding_seen_v1', '1')
    },
    ['auth', JSON.stringify({ token: 'permission-token', user: USER, isLoggedIn: true })],
  )
}

async function installPermissionBackend(page: Page) {
  let applicationCount = 0
  let entitlementEnabled = false
  const cancelledApplications: string[] = []
  const confirmedApplications: string[] = []
  const unexpectedRequests: string[] = []

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname

    // Keep Vite source modules such as /src/api/... out of the backend mock.
    if (!path.startsWith('/api/')) return route.continue()

    // AppShell loads the personal tenant for navigation; this page never
    // starts, resumes, or otherwise depends on a chat Run.
    if (path === '/api/v1/tenants' && request.method() === 'GET') {
      return json(route, [
        { id: 'tenant-permission', name: '个人空间', is_personal: true, role: 'owner' },
      ])
    }
    if (path === '/api/v1/tenants/tenant-permission/sessions' && request.method() === 'GET') {
      return json(route, [])
    }

    if (path === '/api/v0/market-permissions' && request.method() === 'GET') {
      return json(route, [entitlementEnabled ? STAR_ENABLED : STAR_NOT_APPLIED])
    }

    if (path === '/api/v0/market-permissions/star/applications' && request.method() === 'POST') {
      applicationCount += 1
      const idempotencyKey = request.postDataJSON().idempotency_key as string
      if (!idempotencyKey.startsWith('permission-start-')) {
        unexpectedRequests.push(`invalid start payload: ${JSON.stringify(request.postDataJSON())}`)
        return json(route, { detail: 'invalid idempotency key' }, 422)
      }
      return json(route, {
        application_id: `application-${applicationCount}`,
        market: 'star',
        status: 'open',
        assessment_id: null,
        started_at: '2026-07-27T01:00:00Z',
        completed_at: null,
      })
    }

    const profileMatch = path.match(/^\/api\/v0\/market-permissions\/applications\/(application-\d+)\/profile$/)
    if (profileMatch && request.method() === 'PUT') {
      expect(request.postDataJSON()).toEqual({
        declared_average_assets_20d: '500000',
        securities_experience_months: 24,
        risk_level: 'C4',
      })
      return json(route, {
        assessment_id: `assessment-${profileMatch[1]}`,
        market: 'star',
        decision: 'passed',
        failed_conditions: null,
        rule_version: 'star-access-2026-07',
      })
    }

    const cancelMatch = path.match(/^\/api\/v0\/market-permissions\/applications\/(application-\d+)\/cancel$/)
    if (cancelMatch && request.method() === 'POST') {
      cancelledApplications.push(cancelMatch[1])
      return json(route, {
        application_id: cancelMatch[1],
        market: 'star',
        status: 'cancelled',
        assessment_id: `assessment-${cancelMatch[1]}`,
        started_at: '2026-07-27T01:00:00Z',
        completed_at: '2026-07-27T01:01:00Z',
      })
    }

    const confirmMatch = path.match(/^\/api\/v0\/market-permissions\/applications\/(application-\d+)\/confirm$/)
    if (confirmMatch && request.method() === 'POST') {
      expect(request.postDataJSON()).toMatchObject({
        disclosure_version: 'star-risk-disclosure-2026-07',
      })
      confirmedApplications.push(confirmMatch[1])
      entitlementEnabled = true
      return json(route, STAR_ENABLED)
    }

    unexpectedRequests.push(`${request.method()} ${path}`)
    return json(route, { detail: `unexpected API route: ${path}` }, 500)
  })

  return { cancelledApplications, confirmedApplications, unexpectedRequests }
}

test('eligible investor can cancel an application and later complete a new one without a chat Run', async ({
  page,
  context,
}) => {
  await seedAuthenticatedUser(context)
  const backend = await installPermissionBackend(page)

  await page.goto('/market-permissions/star/apply')
  await expect(page.getByRole('heading', { name: '开通科创板交易权限' })).toBeVisible()

  async function submitEligibleProfile() {
    await page.getByLabel('最近 20 个交易日日均证券资产').fill('500000')
    await page.getByLabel('证券交易经验月数').fill('24')
    await page.getByRole('button', { name: '检查开通条件' }).click()
    await expect(page.getByRole('heading', { name: '阅读风险揭示书并最终确认' })).toBeVisible()
  }

  await submitEligibleProfile()
  await page.getByRole('button', { name: '取消申请' }).click()
  await expect(page.getByRole('heading', { name: '申请已取消' })).toBeVisible()
  expect(backend.cancelledApplications).toEqual(['application-1'])

  await page.goto('/market-permissions/star/apply')
  await submitEligibleProfile()
  await page.getByRole('checkbox', { name: '我已完整阅读并理解以上风险揭示内容。' }).check()
  await page.getByRole('button', { name: '最终确认并开通' }).click()

  await expect(page.getByRole('heading', { name: '科创板权限已开通' })).toBeVisible()
  expect(backend.confirmedApplications).toEqual(['application-2'])
  expect(backend.unexpectedRequests).toEqual([])
})
