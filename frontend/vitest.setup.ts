/**
 * frontend/vitest.setup.ts
 *
 * Per-test setup. Registers @testing-library/jest-dom matchers (toBeInTheDocument
 * etc.) and clears jsdom localStorage between tests so persistent state from
 * one test doesn't leak into the next (auth store / report streaming token).
 */

import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach } from 'vitest'

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  localStorage.clear()
})
