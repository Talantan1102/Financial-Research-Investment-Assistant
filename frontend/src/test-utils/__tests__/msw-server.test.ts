import { describe, expect, it } from 'vitest'
import { server } from '@/test-utils/msw-server'

describe('msw-server', () => {
  it('exports a configured msw server with listen / resetHandlers / close', () => {
    expect(server).toBeDefined()
    expect(typeof server.listen).toBe('function')
    expect(typeof server.resetHandlers).toBe('function')
    expect(typeof server.close).toBe('function')
  })
})
