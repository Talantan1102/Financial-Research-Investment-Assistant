import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

import {
  addPersonaItem,
  deletePersonaItem,
  fetchPersona,
  updatePersonaItem,
} from '@/api/personaApi'

const BASE = '/api/v0/persona'

const server = setupServer()

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterAll(() => server.close())
beforeEach(() => server.resetHandlers())

describe('personaApi', () => {
  it('GET /api/v0/persona returns parsed PersonaListResponse', async () => {
    server.use(
      http.get(BASE, () =>
        HttpResponse.json({
          user_declared: [
            {
              id: '00000000-0000-0000-0000-000000000001',
              text: '保守稳健',
              source: 'user',
              position: 0,
              created_at: '2026-05-17T00:00:00+00:00',
              updated_at: '2026-05-17T00:00:00+00:00',
            },
          ],
          agent_inferred: [],
        })
      )
    )

    const data = await fetchPersona()
    expect(data.user_declared).toHaveLength(1)
    expect(data.user_declared[0].text).toBe('保守稳健')
  })

  it('POST /api/v0/persona/items returns created item', async () => {
    server.use(
      http.post(`${BASE}/items`, async ({ request }) => {
        const body = (await request.json()) as { text: string; target_section: string }
        return HttpResponse.json(
          {
            id: '00000000-0000-0000-0000-000000000002',
            text: body.text,
            source: body.target_section,
            position: 1,
            created_at: '2026-05-17T00:00:00+00:00',
            updated_at: '2026-05-17T00:00:00+00:00',
          },
          { status: 201 }
        )
      })
    )

    const item = await addPersonaItem({ text: '新条', target_section: 'user' })
    expect(item.text).toBe('新条')
    expect(item.source).toBe('user')
  })

  it('PATCH /api/v0/persona/items/{id} returns updated item with upgraded source', async () => {
    server.use(
      http.patch(`${BASE}/items/:id`, () =>
        HttpResponse.json({
          id: '00000000-0000-0000-0000-000000000003',
          text: '改后',
          source: 'user',
          position: 3,
          created_at: '2026-05-17T00:00:00+00:00',
          updated_at: '2026-05-17T00:00:00+00:00',
        })
      )
    )

    const item = await updatePersonaItem('00000000-0000-0000-0000-000000000003', '改后')
    expect(item.source).toBe('user')
    expect(item.text).toBe('改后')
  })

  it('DELETE /api/v0/persona/items/{id} resolves on 204', async () => {
    server.use(http.delete(`${BASE}/items/:id`, () => new HttpResponse(null, { status: 204 })))
    await expect(
      deletePersonaItem('00000000-0000-0000-0000-000000000004')
    ).resolves.toBeUndefined()
  })

  it('GET error throws with status', async () => {
    server.use(http.get(BASE, () => new HttpResponse('boom', { status: 500 })))
    await expect(fetchPersona()).rejects.toThrow(/500/)
  })
})
