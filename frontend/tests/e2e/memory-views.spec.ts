/**
 * frontend/tests/e2e/memory-views.spec.ts
 *
 * Plan 7B e2e — 三视图组件渲染 + Cytoscape canvas + 一键否决 + onboarding.
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

async function suppressOnboarding(
  context: import('@playwright/test').BrowserContext,
) {
  await context.addInitScript(() => {
    window.localStorage.setItem('memory_onboarding_seen_v1', '1')
  })
}

async function stubMemoryEndpoints(page: import('@playwright/test').Page) {
  // Playwright matches routes in registration order — later wins.
  // 先注册 catch-all 再注册具体 endpoint, 跟 Plan 7A memory-page.spec.ts 一致.
  await page.route(`${API_HOST}/**`, async (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        data: { items: [], total: 0 },
      }),
    }),
  )
  await page.route(`${API_HOST}/api/v0/memory/graph`, async (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        nodes: [
          {
            node_id: 'n1',
            entity_type: 'User',
            entity_label: '我',
            properties: {},
          },
          {
            node_id: 'n2',
            entity_type: 'Stock',
            entity_label: '茅台',
            properties: {},
          },
        ],
        edges: [
          {
            edge_id: 'e1',
            source_node_id: 'n1',
            target_node_id: 'n2',
            rel_type: 'HOLDS',
            valid_from: '2025-01-01',
            valid_to: null,
            importance: 0.9,
            reasoning: '重仓',
          },
        ],
      }),
    }),
  )
  await page.route(`${API_HOST}/api/v0/memory/timeline*`, async (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            edge_id: 'e1',
            rel_type: 'HOLDS',
            source_label: '我',
            target_label: '茅台',
            valid_from: '2025-01-01',
            valid_to: null,
            importance: 0.9,
            invalidated_at: null,
          },
        ],
        total: 1,
        page: 1,
        page_size: 50,
      }),
    }),
  )
  await page.route(`${API_HOST}/api/v0/memory/audit`, async (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            edge_id: 'e_inv',
            rel_type: 'HOLDS',
            source_label: '我',
            target_label: '茅台 (旧)',
            invalidated_at: '2025-09-01T00:00:00Z',
            invalidated_by_edge_id: null,
            original_reasoning: '用户更正',
          },
        ],
        total: 1,
      }),
    }),
  )
  await page.route(
    `${API_HOST}/api/v0/memory/edges/*/invalidate`,
    async (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          edge_id: 'e1',
          invalidated_at: '2026-05-11T00:00:00Z',
          status: 'invalidated',
        }),
      }),
  )
  await page.route(`${API_HOST}/api/v0/memory/blocks`, async (route) =>
    route.fulfill({
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
    }),
  )
}

test.describe('Memory page views (Plan 7B)', () => {
  test('three tabs render with real components (Graph cytoscape)', async ({
    context,
    page,
  }) => {
    await seedAuth(context)
    await suppressOnboarding(context)
    await stubMemoryEndpoints(page)

    await page.goto('/memory')
    await expect(page.getByTestId('memory-page')).toBeVisible()
    await expect(page.getByTestId('memory-tab-graph')).toBeVisible()
    await expect(page.getByTestId('memory-tab-timeline')).toBeVisible()
    await expect(page.getByTestId('memory-tab-audit')).toBeVisible()

    // Graph tab — cytoscape mounts a <canvas> element on real browser
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 8000 })
  })

  test('Timeline tab renders bar element', async ({ context, page }) => {
    await seedAuth(context)
    await suppressOnboarding(context)
    await stubMemoryEndpoints(page)

    await page.goto('/memory')
    await page.getByTestId('memory-tab-timeline').click()
    await expect(page.getByTestId('timeline-bar-e1')).toBeVisible({
      timeout: 5000,
    })
    await expect(page.getByTestId('timeline-count')).toContainText('1 条')
  })

  test('Audit tab lists invalidated row + active mode invalidate flow', async ({
    context,
    page,
  }) => {
    await seedAuth(context)
    await suppressOnboarding(context)
    await stubMemoryEndpoints(page)

    await page.goto('/memory')
    await page.getByTestId('memory-tab-audit').click()
    // 默认 audit 模式 — 显示 invalidated 历史
    await expect(page.getByText('茅台 (旧)')).toBeVisible({ timeout: 5000 })

    // 切到 active mode → 列出 active edge → 一键否决
    await page.getByTestId('toggle-active').click()
    await expect(page.getByTestId('invalidate-btn-e1')).toBeVisible({
      timeout: 5000,
    })
    await page.getByTestId('invalidate-btn-e1').click()
    // Popconfirm OK button (antd v5 中文按钮可能含空格 "否 决")
    await page.getByRole('button', { name: /^否\s*决$/ }).click()
    // 期待 success message
    await expect(page.getByText(/已否决/)).toBeVisible({ timeout: 3000 })
  })

  test('Onboarding modal pops on first visit and persists seen flag', async ({
    context,
    page,
  }) => {
    await seedAuth(context)
    // do NOT suppress onboarding for this test
    await stubMemoryEndpoints(page)

    await page.goto('/')
    // 800ms 微延迟弹 — antd modal root 包了 hidden wrapper, 直接 getByText
    // 验内容比 testid+visible 更稳 (antd 的 modal-root 在 mount 后 hidden=false
    // 后才显示, jsdom/playwright 检测时序较严).
    await expect(page.getByText(/我会记住您的投资偏好和持仓/)).toBeVisible({
      timeout: 5000,
    })
    await page.getByTestId('onboarding-confirm').click()
    await expect(
      page.getByText(/我会记住您的投资偏好和持仓/),
    ).not.toBeVisible({ timeout: 3000 })

    // reload — 不再弹 (localStorage 标记)
    await page.reload()
    await page.waitForTimeout(1500)
    await expect(
      page.getByText(/我会记住您的投资偏好和持仓/),
    ).not.toBeVisible()
  })

  test.skip(
    'Chat [查看](#mem-xxx) anchor → /memory navigation (dogfood)',
    async () => {
      // 此 case 需要 chat 页 ship 完整 + 真消息流; 留 manual dogfood 验.
      // vitest case 已 cover renderer 的 click 拦截 + 跳转行为.
    },
  )
})
