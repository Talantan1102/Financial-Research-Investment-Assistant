import { expect, test, type BrowserContext, type Page, type Route } from '@playwright/test'

const USER = {
  id: 'action-user',
  username: 'action-user',
  email: 'action@example.test',
  is_active: true,
  created_at: '2026-07-27T01:00:00Z',
}
const TENANT_ID = 'tenant-action'
const SESSION_ID = 'session-action'
const OLD_RUN_ID = 'run-action-old'
const NEW_RUN_ID = 'run-action-new'
const OUTCOME = {
  code: 'action_required' as const,
  action_type: 'apply_market_permission',
  action_url: '/market-permissions/star/apply',
  action_label: '申请科创板权限',
  resume_hint: '完成申请后回来继续下单',
  intent_summary: '买入中芯国际 100 股',
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function seedAuthenticatedUser(context: BrowserContext) {
  await context.addInitScript(
    ([key, value]: [string, string]) => {
      window.localStorage.setItem(key, value)
      window.localStorage.setItem('memory_onboarding_seen_v1', '1')
    },
    ['auth', JSON.stringify({ token: 'action-token', user: USER, isLoggedIn: true })],
  )
}

async function installCompletedActionBackend(page: Page) {
  const createdRuns: Array<{ prompt: string; replaces_run_id: unknown }> = []
  const resumeCalls: string[] = []
  const unexpectedRequests: string[] = []
  // Vite serves source files below /src/api/.  Scope the mock to the actual
  // backend prefix so it cannot intercept those frontend modules.
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/tenants' && request.method() === 'GET') {
      return json(route, [{ id: TENANT_ID, name: '个人空间', is_personal: true, role: 'owner' }])
    }
    if (path === `/api/v1/tenants/${TENANT_ID}/sessions` && request.method() === 'GET') {
      return json(route, [])
    }
    if (path === `/api/v1/tenants/${TENANT_ID}/sessions/${SESSION_ID}` && request.method() === 'GET') {
      return json(route, {
        id: SESSION_ID, tenant_id: TENANT_ID, created_by_user_id: USER.id, title: '开通权限后继续',
        created_at: '2026-07-27T01:00:00Z', updated_at: '2026-07-27T01:01:00Z', archived_at: null,
        messages: [{ id: 'message-action', role: 'assistant', content: '请先完成权限申请。', status: 'complete', created_at: '2026-07-27T01:01:00Z' }],
        has_more: false, active_run_id: null, active_run_status: null, active_pause_id: null,
        active_pause_type: null, active_pause_request: null, revisions: [], revisions_has_more: false,
        revisions_next_cursor: null, latest_run_id: OLD_RUN_ID, latest_run_status: 'completed',
        latest_run_outcome: OUTCOME,
      })
    }
    if (path === `/api/v1/tenants/${TENANT_ID}/runs` && request.method() === 'POST') {
      const body = request.postDataJSON() as { prompt: string; replaces_run_id?: unknown }
      createdRuns.push({ prompt: body.prompt, replaces_run_id: body.replaces_run_id ?? null })
      return json(route, {
        id: NEW_RUN_ID, tenant_id: TENANT_ID, session_id: SESSION_ID, created_by_user_id: USER.id,
        run_type: 'chat', status: 'queued', replaces_run_id: null, retry_count: 0,
        created_at: '2026-07-27T01:02:00Z', queued_at: '2026-07-27T01:02:00Z', finished_at: null,
        error_code: null, error_message: null, outcome: null,
      }, 201)
    }
    if (path === `/api/v1/tenants/${TENANT_ID}/runs/${NEW_RUN_ID}/events` && request.method() === 'GET') {
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
    }
    if (path.includes('/resume') && request.method() === 'POST') {
      resumeCalls.push(path)
      return json(route, { detail: 'completed runs cannot resume' }, 409)
    }
    unexpectedRequests.push(`${request.method()} ${path}`)
    return json(route, { detail: 'unexpected API route' }, 500)
  })
  return { createdRuns, resumeCalls, unexpectedRequests }
}

test('external action ends the old Run and continue creates a new independent Run', async ({ page, context }) => {
  await seedAuthenticatedUser(context)
  const backend = await installCompletedActionBackend(page)

  await page.goto(`/chat/${SESSION_ID}`)
  await expect(page.getByRole('link', { name: OUTCOME.action_label })).toBeVisible()
  await page.getByRole('button', { name: '我已完成，继续' }).click()

  await expect.poll(() => backend.createdRuns).toHaveLength(1)
  expect(backend.createdRuns[0]).toEqual({
    prompt: `我已完成外部操作，请重新检查并继续：${OUTCOME.intent_summary}`,
    replaces_run_id: null,
  })
  expect(backend.resumeCalls).toEqual([])
  expect(backend.unexpectedRequests).toEqual([])
})
