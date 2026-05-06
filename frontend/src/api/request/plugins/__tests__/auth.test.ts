/**
 * frontend/src/api/request/plugins/__tests__/auth.test.ts
 *
 * Vitest unit tests for the auth axios plugin. Three scenarios:
 *  1. Successful 200 response — passes through, redirect side-effect not fired.
 *  2. 401 response on a non-/login path — clears localStorage 'auth' and sets
 *     window.location.href = '/login'.
 *  3. 401 response while already on /login — does NOT redirect (avoids loop).
 *
 * We exercise the plugin by attaching it to a fresh axios instance and feeding
 * synthetic responses through `instance.interceptors.response`. This avoids any
 * real network and pins the contract this plugin promises.
 */

import axios, { type AxiosError, type AxiosResponse } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { authPlugin } from '@/api/request/plugins/auth'

// ── helpers ────────────────────────────────────────────────────────────────

/** Build a minimal AxiosError shaped like a real 401 with no body. */
function make401Error(): AxiosError {
  const err = new Error('Request failed with status code 401') as AxiosError
  err.isAxiosError = true
  err.config = { headers: {} } as AxiosError['config']
  err.response = {
    status: 401,
    statusText: 'Unauthorized',
    data: { detail: 'invalid token' },
    headers: {},
    config: { headers: {} } as AxiosResponse['config'],
  } as AxiosResponse
  return err
}

/**
 * Run the plugin's response interceptors against a synthetic value. axios stores
 * interceptor handlers in a private array — we reach in to invoke them directly,
 * which is the same pattern axios.dispatchRequest uses internally.
 */
async function runResponseInterceptors(
  instance: ReturnType<typeof axios.create>,
  outcome: { type: 'fulfilled'; value: AxiosResponse } | { type: 'rejected'; error: unknown },
) {
  // axios.interceptors.response.handlers is internal but stable across axios
  // 1.x — used by countless test suites. Cast through unknown.
  const handlers = (
    instance.interceptors.response as unknown as {
      handlers: Array<{
        fulfilled?: (v: AxiosResponse) => unknown
        rejected?: (e: unknown) => unknown
      } | null>
    }
  ).handlers.filter(Boolean) as Array<{
    fulfilled?: (v: AxiosResponse) => unknown
    rejected?: (e: unknown) => unknown
  }>

  if (outcome.type === 'fulfilled') {
    let chain: unknown = outcome.value
    for (const h of handlers) {
      if (h.fulfilled) chain = await h.fulfilled(chain as AxiosResponse)
    }
    return chain
  }
  for (const h of handlers) {
    if (h.rejected) {
      try {
        return await h.rejected(outcome.error)
      } catch (e) {
        outcome = { type: 'rejected', error: e }
      }
    }
  }
  throw outcome.error
}

// ── window.location stub ───────────────────────────────────────────────────

let originalLocation: Location

beforeEach(() => {
  originalLocation = window.location
  // jsdom location is read-only via the prototype getter; replace with a
  // mutable plain object that the plugin treats interchangeably.
  Object.defineProperty(window, 'location', {
    value: {
      pathname: '/',
      href: 'http://localhost/',
    },
    writable: true,
    configurable: true,
  })
})

afterEach(() => {
  Object.defineProperty(window, 'location', {
    value: originalLocation,
    writable: true,
    configurable: true,
  })
  vi.restoreAllMocks()
})

// ── tests ──────────────────────────────────────────────────────────────────

describe('authPlugin response interceptor', () => {
  it('passes 200 responses through unchanged (no redirect side-effect)', async () => {
    const instance = axios.create()
    authPlugin.preinstall?.(instance)

    const ok: AxiosResponse = {
      data: { hello: 'world' },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: { headers: {} } as AxiosResponse['config'],
    }

    const result = await runResponseInterceptors(instance, {
      type: 'fulfilled',
      value: ok,
    })

    expect((result as AxiosResponse).status).toBe(200)
    expect(window.location.href).toBe('http://localhost/')
  })

  it('on 401, removes auth localStorage and redirects to /login', async () => {
    localStorage.setItem(
      'auth',
      JSON.stringify({ token: 'stale', user: null, isLoggedIn: true }),
    )

    const instance = axios.create()
    authPlugin.preinstall?.(instance)

    await expect(
      runResponseInterceptors(instance, {
        type: 'rejected',
        error: make401Error(),
      }),
    ).rejects.toBeDefined()

    expect(localStorage.getItem('auth')).toBeNull()
    expect(window.location.href).toBe('/login')
  })

  it('on 401 while already on /login, does NOT trigger redirect (loop guard)', async () => {
    Object.defineProperty(window, 'location', {
      value: { pathname: '/login', href: 'http://localhost/login' },
      writable: true,
      configurable: true,
    })

    localStorage.setItem('auth', JSON.stringify({ token: 't' }))

    const instance = axios.create()
    authPlugin.preinstall?.(instance)

    await expect(
      runResponseInterceptors(instance, {
        type: 'rejected',
        error: make401Error(),
      }),
    ).rejects.toBeDefined()

    // localStorage 仍被清(plugin 行为) — 但 href 没变(loop guard)
    expect(localStorage.getItem('auth')).toBeNull()
    expect(window.location.href).toBe('http://localhost/login')
  })

  it('on 401 while already on /register, does NOT trigger redirect (loop guard)', async () => {
    Object.defineProperty(window, 'location', {
      value: { pathname: '/register', href: 'http://localhost/register' },
      writable: true,
      configurable: true,
    })

    const instance = axios.create()
    authPlugin.preinstall?.(instance)

    await expect(
      runResponseInterceptors(instance, {
        type: 'rejected',
        error: make401Error(),
      }),
    ).rejects.toBeDefined()

    expect(window.location.href).toBe('http://localhost/register')
  })
})

describe('authPlugin request interceptor', () => {
  it('attaches Bearer token from localStorage when present', async () => {
    localStorage.setItem(
      'auth',
      JSON.stringify({ token: 'tk-abc', user: null, isLoggedIn: true }),
    )

    const instance = axios.create()
    authPlugin.preinstall?.(instance)

    const handlers = (
      instance.interceptors.request as unknown as {
        handlers: Array<{
          fulfilled?: (
            v: { headers: Record<string, string> },
          ) => Promise<{ headers: Record<string, string> }> | { headers: Record<string, string> }
        } | null>
      }
    ).handlers.filter(Boolean) as Array<{
      fulfilled?: (
        v: { headers: Record<string, string> },
      ) => Promise<{ headers: Record<string, string> }> | { headers: Record<string, string> }
    }>

    let cfg: { headers: Record<string, string> } = { headers: {} }
    for (const h of handlers) {
      if (h.fulfilled) cfg = await h.fulfilled(cfg)
    }
    expect(cfg.headers.Authorization).toBe('Bearer tk-abc')
  })

  it('does not attach Authorization header when no token in localStorage', async () => {
    const instance = axios.create()
    authPlugin.preinstall?.(instance)

    const handlers = (
      instance.interceptors.request as unknown as {
        handlers: Array<{
          fulfilled?: (
            v: { headers: Record<string, string> },
          ) => Promise<{ headers: Record<string, string> }> | { headers: Record<string, string> }
        } | null>
      }
    ).handlers.filter(Boolean) as Array<{
      fulfilled?: (
        v: { headers: Record<string, string> },
      ) => Promise<{ headers: Record<string, string> }> | { headers: Record<string, string> }
    }>

    let cfg: { headers: Record<string, string> } = { headers: {} }
    for (const h of handlers) {
      if (h.fulfilled) cfg = await h.fulfilled(cfg)
    }
    expect(cfg.headers.Authorization).toBeUndefined()
  })
})
