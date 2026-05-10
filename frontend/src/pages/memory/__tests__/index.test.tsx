/**
 * frontend/src/pages/memory/__tests__/index.test.tsx
 *
 * L0 RTL — tab 切换 + working blocks 卡 渲染.
 * Plan 7A Task 8.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import MemoryPage from '@/pages/memory'
import { server } from '@/test-utils/msw-server'

const API_BASE = ((import.meta.env.VITE_API_BASE as string) ?? '').replace(
  /\/$/,
  '',
)

beforeEach(() => {
  server.use(
    http.get(`${API_BASE}/api/v0/memory/graph`, () =>
      HttpResponse.json({ nodes: [], edges: [] }),
    ),
    http.get(`${API_BASE}/api/v0/memory/timeline`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 }),
    ),
    http.get(`${API_BASE}/api/v0/memory/audit`, () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
    http.get(`${API_BASE}/api/v0/memory/blocks`, () =>
      HttpResponse.json({
        blocks: [
          {
            block_name: 'persona',
            content: 'long-term value investor',
            token_count: 5,
            max_tokens: 500,
            updated_at: '2026-05-11T00:00:00Z',
          },
        ],
      }),
    ),
  )
})

describe('MemoryPage', () => {
  it('renders three tabs and switches between them', async () => {
    render(
      <MemoryRouter>
        <MemoryPage />
      </MemoryRouter>,
    )

    // 三 tab 都可见
    expect(screen.getByTestId('memory-tab-graph')).toBeInTheDocument()
    expect(screen.getByTestId('memory-tab-timeline')).toBeInTheDocument()
    expect(screen.getByTestId('memory-tab-audit')).toBeInTheDocument()

    // 初始默认 graph tab (placeholder 可见)
    expect(screen.getByTestId('memory-graph-placeholder')).toBeInTheDocument()

    // 切到 timeline
    fireEvent.click(screen.getByTestId('memory-tab-timeline'))
    await waitFor(() =>
      expect(
        screen.getByTestId('memory-timeline-placeholder'),
      ).toBeInTheDocument(),
    )

    // 切到 audit
    fireEvent.click(screen.getByTestId('memory-tab-audit'))
    await waitFor(() =>
      expect(
        screen.getByTestId('memory-audit-placeholder'),
      ).toBeInTheDocument(),
    )
  })

  it('renders working blocks card from /blocks', async () => {
    render(
      <MemoryRouter>
        <MemoryPage />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByText(/persona/i)).toBeInTheDocument(),
    )
    expect(
      screen.getByText(/long-term value investor/),
    ).toBeInTheDocument()
  })
})
