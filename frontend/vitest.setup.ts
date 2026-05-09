/**
 * frontend/vitest.setup.ts
 *
 * Per-test setup. Registers @testing-library/jest-dom matchers (toBeInTheDocument
 * etc.) and clears jsdom localStorage between tests so persistent state from
 * one test doesn't leak into the next (auth store / report streaming token).
 *
 * Also wires the msw server lifecycle so every vitest test file gets request
 * interception out of the box (handlers registered per-test via server.use()).
 */

import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest'
import { server } from '@/test-utils/msw-server'

// react-window (VariableSizeList) uses ResizeObserver internally; jsdom doesn't
// provide it. Stub it so tests don't throw "ResizeObserver is not defined".
class _ResizeObserverStub { observe() {} unobserve() {} disconnect() {} }
// @ts-expect-error jsdom shim
globalThis.ResizeObserver = globalThis.ResizeObserver ?? _ResizeObserverStub

// react-window also calls getBoundingClientRect on its outer container to
// determine visible area. In jsdom all elements return 0. Provide a fallback
// offsetHeight so VariableSizeList renders at least one row in tests.
Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
  configurable: true,
  get() { return (this as HTMLElement).style?.height ? parseInt((this as HTMLElement).style.height, 10) || 600 : 600 },
})

// antd responsive components (List, Grid, etc.) use window.matchMedia which
// is not implemented in jsdom. Provide a no-op stub so antd doesn't throw.
if (typeof window !== 'undefined' && !window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  })
}

// msw server lifecycle
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterAll(() => server.close())

// localStorage reset (auth store / report streaming token)
beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  localStorage.clear()
  server.resetHandlers()
})
