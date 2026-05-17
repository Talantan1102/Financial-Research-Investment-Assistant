/**
 * frontend/tests/e2e/memory-persona.spec.ts
 *
 * Plan Task 16 — Persona tab: 渲染 + add / edit-upgrade / delete 四个 e2e.
 *
 * Backend mock: page.route() 拦截 /api/v0/persona/* — 不依赖真后端.
 * Stub 维护 in-memory 状态, add/edit/delete 操作后 GET 拉回更新数据.
 */

import { expect, test, type BrowserContext, type Page } from '@playwright/test'

// personaApi.ts 用 VITE_API_BASE(默认空串),所以请求走 Vite dev server 相对路径.
// page.route() 的 glob 模式 '**/api/v0/...' 匹配实际的 localhost:5183 请求.
const API_PREFIX = '**/api/v0/persona'

const FAKE_USER = {
  id: 'u-1',
  email: 'test@example.com',
  display_name: 'test',
}

async function seedAuth(context: BrowserContext) {
  await context.addInitScript(([authKey, payload]: [string, string]) => {
    window.localStorage.setItem(authKey, payload)
  }, ['auth', JSON.stringify({ token: 'tk-test', user: FAKE_USER, isLoggedIn: true })])
}

async function suppressOnboarding(context: BrowserContext) {
  await context.addInitScript(() => {
    window.localStorage.setItem('memory_onboarding_seen_v1', '1')
  })
}

async function stubPersonaEndpoints(page: Page) {
  let userItems = [
    {
      id: 'u-item-1',
      text: '已声明的偏好',
      source: 'user' as const,
      position: 0,
      created_at: '2026-05-17T00:00:00+00:00',
      updated_at: '2026-05-17T00:00:00+00:00',
    },
  ]
  let agentItems = [
    {
      id: 'a-item-1',
      text: '关注新能源',
      source: 'agent' as const,
      position: 0,
      created_at: '2026-05-17T00:00:00+00:00',
      updated_at: '2026-05-17T00:00:00+00:00',
    },
  ]

  // 注册顺序: 先具体路径(first-match-wins), 后宽泛路径
  // PATCH/DELETE /api/v0/persona/items/:id
  await page.route(`${API_PREFIX}/items/*`, async (route) => {
    const url = new URL(route.request().url())
    const id = url.pathname.split('/').pop()!
    if (route.request().method() === 'PATCH') {
      const body = JSON.parse(route.request().postData() ?? '{}')
      // 模拟 agent → user 升级
      const wasAgent = id === 'a-item-1'
      const updated = {
        id,
        text: body.text,
        source: 'user' as const,
        position: userItems.length,
        created_at: '2026-05-17T00:00:00+00:00',
        updated_at: '2026-05-17T00:00:00+00:00',
      }
      if (wasAgent) {
        agentItems = agentItems.filter((i) => i.id !== id)
        userItems = [...userItems, updated]
      } else {
        userItems = userItems.map((i) => (i.id === id ? { ...i, text: body.text } : i))
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(updated),
      })
      return
    }
    if (route.request().method() === 'DELETE') {
      userItems = userItems.filter((i) => i.id !== id)
      agentItems = agentItems.filter((i) => i.id !== id)
      await route.fulfill({ status: 204 })
      return
    }
    await route.fulfill({ status: 404 })
  })
  // POST /api/v0/persona/items
  await page.route(`${API_PREFIX}/items`, async (route) => {
    if (route.request().method() === 'POST') {
      const body = JSON.parse(route.request().postData() ?? '{}')
      const item = {
        id: `u-${Date.now()}`,
        text: body.text,
        source: body.target_section,
        position: userItems.length,
        created_at: '2026-05-17T00:00:00+00:00',
        updated_at: '2026-05-17T00:00:00+00:00',
      }
      userItems = [...userItems, item]
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(item),
      })
      return
    }
    await route.fulfill({ status: 404 })
  })
  // GET /api/v0/persona — must be last (glob matches sub-paths too)
  await page.route(`${API_PREFIX}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ user_declared: userItems, agent_inferred: agentItems }),
    })
  })
}

test('memory persona tab is default and renders items', async ({ page, context }) => {
  await seedAuth(context)
  await suppressOnboarding(context)
  await stubPersonaEndpoints(page)

  await page.goto('/memory')

  await expect(page.getByText('你声明的')).toBeVisible()
  await expect(page.getByText('agent 观察到的')).toBeVisible()
  await expect(page.getByText('已声明的偏好')).toBeVisible()
  await expect(page.getByText('关注新能源')).toBeVisible()
})

test('add a new persona item appears in user section', async ({ page, context }) => {
  await seedAuth(context)
  await suppressOnboarding(context)
  await stubPersonaEndpoints(page)

  await page.goto('/memory')
  await page.getByRole('button', { name: /手动添加一条/ }).click()
  // 等 antd Modal portal 渲染完成
  await page.waitForSelector('.ant-modal-content', { timeout: 5000 })
  await page.getByPlaceholder(/输入一条画像/).fill('新加的偏好')
  // antd Modal okText="保存" 的 OK 按钮: 用 .ant-modal-footer 内的 button[type=button]
  await page.locator('.ant-modal-footer button.ant-btn-primary').click()

  await expect(page.getByText('新加的偏好')).toBeVisible()
})

test('edit agent item upgrades to user section', async ({ page, context }) => {
  await seedAuth(context)
  await suppressOnboarding(context)
  await stubPersonaEndpoints(page)

  await page.goto('/memory')
  await page.getByTestId('persona-edit-a-item-1').click()
  // Input.TextArea 渲染为 <textarea>; 等待其出现再操作
  const editArea = page.locator('textarea').first()
  await editArea.waitFor({ timeout: 3000 })
  await editArea.fill('关注新能源 + 储能')
  await page.getByTestId('persona-save-a-item-1').click()

  await expect(page.getByText('关注新能源 + 储能')).toBeVisible()
})

test('delete an item removes it', async ({ page, context }) => {
  await seedAuth(context)
  await suppressOnboarding(context)
  await stubPersonaEndpoints(page)

  await page.goto('/memory')
  await page.getByTestId('persona-delete-u-item-1').click()
  await page.getByRole('button', { name: /^确\s*认$/ }).click()

  await expect(page.getByText('已声明的偏好')).not.toBeVisible()
})
