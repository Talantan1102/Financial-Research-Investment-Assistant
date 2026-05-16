/**
 * frontend/src/pages/memory/__tests__/index.test.tsx
 *
 * L0 RTL — tab 切换 + working blocks 卡 渲染.
 * Plan 7A Task 8 起底, Plan 7B Task 2 替换 Graph placeholder 为 MemoryGraph
 * 真实组件后, 把对 placeholder 的断言换成对 graph empty state / 其他 tab
 * placeholder 的断言.
 * Plan Task 15: 加 persona tab 为默认, 更新断言.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MemoryPage from '@/pages/memory'
import { server } from '@/test-utils/msw-server'

// Mock cytoscape — jsdom canvas missing, MemoryGraph empty state path doesn't
// hit the cytoscape mount but we still install the stub for safety.
vi.mock('react-cytoscapejs', () => ({
  default: () => <div data-testid="cyto-stub" />,
}))

const API_BASE = ((import.meta.env.VITE_API_BASE as string) ?? '').replace(
  /\/$/,
  '',
)

beforeEach(() => {
  server.use(
    http.get(`${API_BASE}/api/v0/persona`, () =>
      HttpResponse.json({ user_declared: [], agent_inferred: [] }),
    ),
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
  it('renders four tabs with correct testids', () => {
    render(
      <MemoryRouter>
        <MemoryPage />
      </MemoryRouter>,
    )

    expect(screen.getByTestId('memory-tab-persona')).toBeInTheDocument()
    expect(screen.getByTestId('memory-tab-graph')).toBeInTheDocument()
    expect(screen.getByTestId('memory-tab-timeline')).toBeInTheDocument()
    expect(screen.getByTestId('memory-tab-audit')).toBeInTheDocument()
  })

  it('defaults to persona tab (empty persona state visible)', async () => {
    render(
      <MemoryRouter>
        <MemoryPage />
      </MemoryRouter>,
    )

    // persona empty state text (from MemoryPersona when items=[])
    await waitFor(() =>
      expect(screen.getByText(/还没有任何记忆/)).toBeInTheDocument(),
    )
  })

  it('switches between tabs', async () => {
    render(
      <MemoryRouter>
        <MemoryPage />
      </MemoryRouter>,
    )

    // click graph tab
    fireEvent.click(screen.getByTestId('memory-tab-graph'))
    await waitFor(() =>
      expect(screen.getByText(/还没有 memory/)).toBeInTheDocument(),
    )

    // click timeline tab
    fireEvent.click(screen.getByTestId('memory-tab-timeline'))
    await waitFor(() =>
      expect(screen.getByText(/还没有时间序列/)).toBeInTheDocument(),
    )

    // click audit tab
    fireEvent.click(screen.getByTestId('memory-tab-audit'))
    await waitFor(() =>
      expect(screen.getByText(/暂无被纠正的记录/)).toBeInTheDocument(),
    )

    // click back to persona tab
    fireEvent.click(screen.getByTestId('memory-tab-persona'))
    await waitFor(() =>
      expect(screen.getByText(/还没有任何记忆/)).toBeInTheDocument(),
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
