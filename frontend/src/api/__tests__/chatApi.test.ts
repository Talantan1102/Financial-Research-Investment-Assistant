import { describe, expect, it, vi } from 'vitest'
import { confirmEscalation } from '@/api/chatApi'

describe('chatApi Run cutover', () => {
  it('posts confirmed escalation to the tenant-scoped Run API', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{}', { status: 200 }),
    )
    await confirmEscalation({
      tenant_id: 'tenant-1',
      session_id: 'session-1',
      packet: {} as never,
    })
    expect(fetchMock.mock.calls[0]?.[0]).toContain(
      '/api/v1/tenants/tenant-1/research-escalations',
    )
    expect(String(fetchMock.mock.calls[0]?.[0])).not.toContain('/api/v0/chat')
    fetchMock.mockRestore()
  })

  it('requires tenant scope before sending an escalation', async () => {
    await expect(
      confirmEscalation({ session_id: 'session-1', packet: {} as never }),
    ).rejects.toThrow('tenant_id is required')
  })
})
