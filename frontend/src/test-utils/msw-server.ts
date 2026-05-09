/**
 * Shared msw server for vitest. Lifecycle is wired in vitest.setup.ts.
 */
import { setupServer } from 'msw/node'

export const server = setupServer()
