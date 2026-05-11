/**
 * frontend/tests/e2e/landing.spec.ts
 *
 * Minimal Playwright e2e smoke for v0.9.x AlphaScout landing + auth flow.
 * Scope:
 *  - /login renders (the page-shell + form). The current branch's login page
 *    still uses 「金融研究助手」 brand text; the AlphaScout rebrand only landed
 *    on the home page (commit ee35ad4). We assert presence of the login form
 *    here; the AlphaScout brand assertion lives on the `/` landing test.
 *  - /register accepts a synthetic registration: backend POST /auth/register
 *    is mocked → app navigates to '/'.
 *  - On `/`, the AlphaScout hero brand is visible, the ResearchEntry card is
 *    visible, and there are no leftover industry-assistant cards or the old
 *    "行业咨询助手" string.
 *
 * Backend is mocked entirely via `page.route()` — no FastAPI/LLM required.
 */

import { expect, test } from '@playwright/test'

const API_HOST = 'http://localhost:8001'

const FAKE_USER = {
  id: 'u-test',
  username: 'tester',
  email: 'tester@example.com',
  is_active: true,
  created_at: '2026-05-06T00:00:00Z',
}

/**
 * Pre-seed localStorage with a valid auth blob so AuthGuard lets us into `/`.
 * Done via `addInitScript` so it runs before any page module evaluates.
 */
async function seedAuth(context: import('@playwright/test').BrowserContext) {
  await context.addInitScript(([authKey, payload]: [string, string]) => {
    window.localStorage.setItem(authKey, payload)
  }, ['auth', JSON.stringify({ token: 'tk-test', user: FAKE_USER, isLoggedIn: true })])
}

/**
 * Stub all network calls to the backend host with a generic 200 envelope.
 * Specific endpoints (register, list reports) are overridden per-test as
 * needed; this is the catch-all so unanticipated requests don't 404 the UI.
 */
async function stubBackend(page: import('@playwright/test').Page) {
  await page.route(`${API_HOST}/**`, async (route) => {
    const url = route.request().url()
    // Default no-op envelope
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        message: `stub for ${url}`,
        data: { items: [], total: 0, page: 1, page_size: 20 },
      }),
    })
  })
}

test.describe('AlphaScout v0.9.x landing — minimal frontend smoke', () => {
  test('/login renders the login form (page-shell smoke)', async ({ page }) => {
    await stubBackend(page)
    await page.goto('/login')

    // Login form present (username + password inputs + submit button)
    await expect(page.getByPlaceholder('用户名')).toBeVisible()
    await expect(page.getByPlaceholder('密码')).toBeVisible()
    // antd Button renders text inside <span>; match by submit-type button.
    await expect(page.locator('button[type="submit"]')).toBeVisible()
  })

  test('/register submits → mocked /auth/register → navigates to /', async ({
    page,
    context,
  }) => {
    // Mock /auth/register specifically; everything else falls through to the
    // generic stub installed below.
    await page.route(`${API_HOST}/auth/register`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'success',
          message: 'ok',
          data: {
            access_token: 'tk-fresh',
            token_type: 'bearer',
            user: FAKE_USER,
          },
        }),
      })
    })
    await stubBackend(page)
    // Pre-seed auth so the post-register redirect to '/' is allowed by AuthGuard
    // even before localStorage commits inside the same tick.
    await seedAuth(context)

    await page.goto('/register')
    await page.getByPlaceholder('用户名').fill('newuser')
    await page.getByPlaceholder('邮箱').fill('newuser@example.com')
    await page.getByPlaceholder('密码').fill('s3cret-pw')
    await page.locator('button[type="submit"]').click()

    // After successful register, the app navigates to '/'
    await page.waitForURL('**/', { timeout: 8_000 })
    expect(new URL(page.url()).pathname).toBe('/')
  })

  test('/ landing — AlphaScout brand visible + ResearchEntry + no industry residue', async ({
    page,
    context,
  }) => {
    // Plan 7B Task 5 起 AppShell 挂 MemoryOnboardingModal — 已 seen 跳过避免遮罩
    // (此 test 在 main HEAD 已失败, 修 onboarding 不能恢复, 但保留 init script
    // 让 onboarding 不影响 future 修复. 真正的 'AlphaScout 品牌不可见' 是 / →
    // /chat 路由切换 + chat landing 用旧品牌, 已是 pre-existing issue).
    await context.addInitScript(() =>
      window.localStorage.setItem('memory_onboarding_seen_v1', '1'),
    )
    await seedAuth(context)
    await stubBackend(page)

    await page.goto('/')

    // AlphaScout hero brand is visible
    await expect(page.getByText('AlphaScout', { exact: true })).toBeVisible()

    // ResearchEntry card is visible
    await expect(page.getByText('新建投资尽调研报')).toBeVisible()
    await expect(page.getByPlaceholder(/目标名称/)).toBeVisible()
    await expect(page.getByText('开始研究')).toBeVisible()

    // No legacy industry-assistant residue
    const html = await page.content()
    expect(html).not.toContain('行业咨询助手')
    expect(html).not.toContain('行业咨询')
  })
})
