import { describe, expect, it } from 'vitest'
import { sseResponse } from '@/test-utils/sse-mock'

describe('sseResponse', () => {
  it('builds a Response with text/event-stream and pre-encoded body', async () => {
    const res = sseResponse([
      { type: 'token', seq: 1, content: 'hi' },
      { type: 'done', seq: 2 },
    ])
    expect(res.headers.get('Content-Type')).toBe('text/event-stream')
    const text = await res.text()
    expect(text).toContain('data: {"type":"token"')
    expect(text).toContain('id: 2')
  })
})
