/**
 * MemoryGraph vitest (Plan 7B Task 2) — 5 项.
 *
 * jsdom 不能真正运行 cytoscape 的 canvas renderer, 所以本测试 mock
 * react-cytoscapejs 为空 div, 只验证组件的数据流 / loading / empty / error /
 * status 分类纯函数. 真 layout / interaction 由 Playwright e2e (Task 8) 验.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/memoryApi'
import {
  classifyEdgeStatus,
  type GraphEdgeLike,
} from '@/components/memory/MemoryGraph.styles'

// Mock cytoscape component — jsdom 没 real canvas.
vi.mock('react-cytoscapejs', () => ({
  default: (props: unknown) => {
    const elements =
      typeof props === 'object' && props !== null && 'elements' in props
        ? (props as { elements: unknown[] }).elements
        : []
    return (
      <div data-testid="cyto-stub">
        cytoscape stub ({Array.isArray(elements) ? elements.length : 0} els)
      </div>
    )
  },
}))

vi.mock('@/api/memoryApi')

const mkEdge = (overrides: Partial<GraphEdgeLike> = {}): GraphEdgeLike => ({
  edge_id: 'e1',
  source_node_id: 'n1',
  target_node_id: 'n2',
  rel_type: 'HOLDS',
  valid_from: '2025-01-01',
  valid_to: null,
  invalidated_at: null,
  importance: 0.9,
  reasoning: null,
  ...overrides,
})

// Import AFTER vi.mock so the mocked cytoscape is in effect.
const { default: MemoryGraph } = await import(
  '@/components/memory/MemoryGraph'
)

describe('<MemoryGraph>', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('renders Spin while loading', () => {
    vi.mocked(api.fetchMemoryGraph).mockReturnValue(new Promise(() => {}))
    render(<MemoryGraph />)
    expect(document.querySelector('.ant-spin')).not.toBeNull()
  })

  it('renders Empty when graph has no nodes', async () => {
    vi.mocked(api.fetchMemoryGraph).mockResolvedValue({
      nodes: [],
      edges: [],
    })
    render(<MemoryGraph />)
    await waitFor(() => {
      expect(screen.getByText(/还没有 memory/)).toBeTruthy()
    })
  })

  it('renders an error notice when API rejects', async () => {
    vi.mocked(api.fetchMemoryGraph).mockRejectedValue(new Error('network down'))
    render(<MemoryGraph />)
    await waitFor(() => {
      expect(screen.getByText(/加载失败.*network down/)).toBeTruthy()
    })
  })

  it('classifyEdgeStatus distinguishes current / ended / invalidated', () => {
    expect(classifyEdgeStatus(mkEdge())).toBe('current')
    expect(classifyEdgeStatus(mkEdge({ valid_to: '2025-06-01' }))).toBe('ended')
    expect(
      classifyEdgeStatus(mkEdge({ invalidated_at: '2025-09-01' })),
    ).toBe('invalidated')
  })

  it('renders the cytoscape container once data arrives', async () => {
    vi.mocked(api.fetchMemoryGraph).mockResolvedValue({
      nodes: [
        { node_id: 'n1', entity_type: 'User', entity_label: '我', properties: {} },
        {
          node_id: 'n2',
          entity_type: 'Stock',
          entity_label: '茅台',
          properties: {},
        },
      ],
      edges: [mkEdge()],
    })
    render(<MemoryGraph />)
    await waitFor(() => {
      expect(screen.getByTestId('cyto-stub')).toBeTruthy()
    })
  })
})
