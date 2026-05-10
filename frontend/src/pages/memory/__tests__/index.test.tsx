/**
 * frontend/src/pages/memory/__tests__/index.test.tsx
 *
 * L0 RTL — tab 切换 + working blocks 卡 渲染.
 * Plan 7A Task 8 起底, Plan 7B Task 2 替换 Graph placeholder 为 MemoryGraph
 * 真实组件后, 把对 placeholder 的断言换成对 graph empty state / 其他 tab
 * placeholder 的断言.
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

    // 默认 Graph tab — empty graph 显示提示 (Plan 7B Task 2 替换 placeholder)
    await waitFor(() =>
      expect(screen.getByText(/还没有 memory/)).toBeInTheDocument(),
    )

    // 切到 timeline (Plan 7B Task 3 已替换 placeholder, 空数据走 empty)
    fireEvent.click(screen.getByTestId('memory-tab-timeline'))
    await waitFor(() =>
      expect(screen.getByText(/还没有时间序列/)).toBeInTheDocument(),
    )

    // 切到 audit (Task 4 之前仍是 placeholder)
    fireEvent.click(screen.getByTestId('memory-tab-audit'))
    await waitFor(() =>
      expect(screen.getByTestId('memory-audit-placeholder')).toBeInTheDocument(),
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
