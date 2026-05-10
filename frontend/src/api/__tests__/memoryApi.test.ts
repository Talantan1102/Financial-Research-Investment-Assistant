/**
 * frontend/src/api/__tests__/memoryApi.test.ts
 *
 * L0 Vitest + msw — 5 endpoint typed client + 1 error path.
 * Plan 7A Task 7.
 */
import { describe, expect, it } from 'vitest'
import { HttpResponse, http } from 'msw'
import {
  fetchMemoryAudit,
  fetchMemoryBlocks,
  fetchMemoryGraph,
  fetchMemoryTimeline,
  invalidateMemoryEdge,
} from '@/api/memoryApi'
import { server } from '@/test-utils/msw-server'

// Match apiUrl() normalization: strip trailing slash so handler patterns
// align with the URL actually fetched (otherwise '//' double-slash drift
// breaks MSW match — same gotcha hit by chatApi tests post .env.local
// override to http://localhost:8001/).
const API_BASE = ((import.meta.env.VITE_API_BASE as string) ?? '').replace(/\/$/, '')

describe('memoryApi', () => {
  it('fetchMemoryGraph GETs /api/v0/memory/graph', async () => {
    server.use(
      http.get(`${API_BASE}/api/v0/memory/graph`, () =>
        HttpResponse.json({
          nodes: [
            {
              node_id: 'n1',
              entity_type: 'Stock',
              entity_label: '600519.SH',
              properties: { name: '茅台' },
            },
          ],
          edges: [],
        }),
      ),
    )
    const res = await fetchMemoryGraph()
    expect(res.nodes).toHaveLength(1)
    expect(res.nodes[0].entity_label).toBe('600519.SH')
  })

  it('fetchMemoryTimeline GETs with query params', async () => {
    server.use(
      http.get(`${API_BASE}/api/v0/memory/timeline`, ({ request }) => {
        const url = new URL(request.url)
        expect(url.searchParams.get('rel_type')).toBe('HOLDS')
        expect(url.searchParams.get('page')).toBe('2')
        return HttpResponse.json({
          items: [],
          total: 0,
          page: 2,
          page_size: 50,
        })
      }),
    )
    const res = await fetchMemoryTimeline({ rel_type: 'HOLDS', page: 2 })
    expect(res.page).toBe(2)
  })

  it('fetchMemoryTimeline omits query string when no filters', async () => {
    server.use(
      http.get(`${API_BASE}/api/v0/memory/timeline`, ({ request }) => {
        const url = new URL(request.url)
        expect(url.search).toBe('')
        return HttpResponse.json({
          items: [],
          total: 0,
          page: 1,
          page_size: 50,
        })
      }),
    )
    const res = await fetchMemoryTimeline()
    expect(res.total).toBe(0)
  })

  it('fetchMemoryAudit GETs /audit', async () => {
    server.use(
      http.get(`${API_BASE}/api/v0/memory/audit`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    )
    const res = await fetchMemoryAudit()
    expect(res.total).toBe(0)
  })

  it('fetchMemoryBlocks GETs /blocks', async () => {
    server.use(
      http.get(`${API_BASE}/api/v0/memory/blocks`, () =>
        HttpResponse.json({
          blocks: [
            {
              block_name: 'persona',
              content: 'value investor',
              token_count: 5,
              max_tokens: 500,
              updated_at: '2026-05-11T00:00:00Z',
            },
          ],
        }),
      ),
    )
    const res = await fetchMemoryBlocks()
    expect(res.blocks[0].block_name).toBe('persona')
  })

  it('invalidateMemoryEdge POSTs to /edges/{id}/invalidate', async () => {
    server.use(
      http.post(`${API_BASE}/api/v0/memory/edges/e1/invalidate`, () =>
        HttpResponse.json({
          edge_id: 'e1',
          invalidated_at: '2026-05-11T01:00:00Z',
          status: 'invalidated',
        }),
      ),
    )
    const res = await invalidateMemoryEdge('e1')
    expect(res.status).toBe('invalidated')
    expect(res.edge_id).toBe('e1')
  })

  it('invalidateMemoryEdge throws on 400 (already invalidated)', async () => {
    server.use(
      http.post(
        `${API_BASE}/api/v0/memory/edges/e2/invalidate`,
        () => new HttpResponse(null, { status: 400 }),
      ),
    )
    await expect(invalidateMemoryEdge('e2')).rejects.toThrow()
  })

  it('invalidateMemoryEdge encodes edge_id', async () => {
    const weirdId = 'a/b%c'
    server.use(
      http.post(
        `${API_BASE}/api/v0/memory/edges/a%2Fb%25c/invalidate`,
        () =>
          HttpResponse.json({
            edge_id: weirdId,
            invalidated_at: '2026-05-11T01:00:00Z',
            status: 'invalidated',
          }),
      ),
    )
    const res = await invalidateMemoryEdge(weirdId)
    expect(res.edge_id).toBe(weirdId)
  })
})
