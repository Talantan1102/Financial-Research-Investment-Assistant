/**
 * frontend/tests/e2e/memory-page.spec.ts
 *
 * Playwright smoke for C.5 Plan 7A /memory page foundation.
 * Scope:
 *  - sidebar 含 Memory 链接 + 点击跳到 /memory 路由
 *  - 三 tab(Graph / Timeline / Audit) 可见 + 可切换
 *  - working blocks 卡片渲染(从 mock /blocks)
 *
 * Backend mock: page.route() 拦截 /api/v0/memory/* — 不依赖真后端.
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

async function seedAuth(context: import('@playwright/test').BrowserContext) {
  await context.addInitScript(([authKey, payload]: [string, string]) => {
    window.localStorage.setItem(authKey, payload)
  }, [
    'auth',
    JSON.stringify({ token: 'tk-test', user: FAKE_USER, isLoggedIn: true }),
  ])
}

async function stubMemoryEndpoints(page: import('@playwright/test').Page) {
  // Playwright matches routes in registration order; later wins. 先注册 catch-all,
  // 再注册具体 endpoint, 让具体 handler 在 catch-all 之前命中.
  await page.route(`${API_HOST}/**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        data: { items: [], total: 0, page: 1, page_size: 20 },
      }),
    })
  })
  await page.route(`${API_HOST}/api/v0/memory/graph`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ nodes: [], edges: [] }),
    })
  })
  await page.route(`${API_HOST}/api/v0/memory/timeline*`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], total: 0, page: 1, page_size: 50 }),
    })
  })
  await page.route(`${API_HOST}/api/v0/memory/audit`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], total: 0 }),
    })
  })
  await page.route(`${API_HOST}/api/v0/memory/blocks`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        blocks: [
          {
            block_name: 'persona',
            content: 'long-term value investor',
            token_count: 5,
            max_tokens: 500,
            updated_at: '2026-05-11T00:00:00Z',
          },
        ],
      }),
    })
  })
}

test.describe('/memory page foundation', () => {
  test('sidebar Memory link navigates to /memory', async ({
    context,
    page,
  }) => {
    // suppress Plan 7B onboarding modal so it doesn't intercept clicks.
    await context.addInitScript(() =>
      window.localStorage.setItem('memory_onboarding_seen_v1', '1'),
    )
    await seedAuth(context)
    await stubMemoryEndpoints(page)

    await page.goto('/')
    const memoryLink = page.getByRole('link', { name: 'Memory' })
    await expect(memoryLink).toBeVisible()
    await memoryLink.click()
    await expect(page).toHaveURL(/\/memory$/)
  })

  test('three tabs visible and switchable', async ({ context, page }) => {
    // suppress onboarding modal in this Plan 7A regression test
    await context.addInitScript(() =>
      window.localStorage.setItem('memory_onboarding_seen_v1', '1'),
    )
    await seedAuth(context)
    await stubMemoryEndpoints(page)

    await page.goto('/memory')
    await expect(page.getByTestId('memory-page')).toBeVisible()
    await expect(page.getByTestId('memory-tab-graph')).toBeVisible()
    await expect(page.getByTestId('memory-tab-timeline')).toBeVisible()
    await expect(page.getByTestId('memory-tab-audit')).toBeVisible()

    // Plan 7B Task 2 起替换 graph placeholder 为 MemoryGraph; 空 graph
    // 走 empty state.
    await expect(page.getByText(/还没有 memory/)).toBeVisible({ timeout: 5000 })

    // 切 timeline (Plan 7B Task 3 起替换为 MemoryTimeline; 空走 empty)
    await page.getByTestId('memory-tab-timeline').click()
    await expect(page.getByText(/还没有时间序列/)).toBeVisible({ timeout: 5000 })

    // 切 audit (Plan 7B Task 4 起替换为 MemoryAuditLog)
    await page.getByTestId('memory-tab-audit').click()
    await expect(page.getByText(/暂无被纠正的记录/)).toBeVisible({ timeout: 5000 })
  })

  test('working blocks card renders persona content', async ({
    context,
    page,
  }) => {
    await context.addInitScript(() =>
      window.localStorage.setItem('memory_onboarding_seen_v1', '1'),
    )
    await seedAuth(context)
    await stubMemoryEndpoints(page)

    await page.goto('/memory')
    await expect(page.getByText('persona', { exact: true })).toBeVisible()
    await expect(page.getByText('long-term value investor')).toBeVisible()
  })
})
