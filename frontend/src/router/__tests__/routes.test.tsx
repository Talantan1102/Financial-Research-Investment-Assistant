import { describe, expect, it } from 'vitest'
import { routes } from '@/router/routes'

describe('routes', () => {
  it('declares /chat / /chat/:session_id / /reports', () => {
    const paths = routes.map((r) => r.path)
    expect(paths).toContain('/chat')
    expect(paths).toContain('/chat/:session_id')
    expect(paths).toContain('/reports')
  })
  it('keeps /research / /research/new / /research/:id / /knowledge / /monitoring / /portfolio', () => {
    const paths = routes.map((r) => r.path)
    expect(paths).toContain('/research')
    expect(paths).toContain('/research/new')
    expect(paths).toContain('/research/:id')
    expect(paths).toContain('/knowledge')
    expect(paths).toContain('/monitoring')
    expect(paths).toContain('/portfolio')
  })
  it('"/" route declared', () => {
    const root = routes.find((r) => r.path === '/')
    expect(root).toBeDefined()
  })
})
