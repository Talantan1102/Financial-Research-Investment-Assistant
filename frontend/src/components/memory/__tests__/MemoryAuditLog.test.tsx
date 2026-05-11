/**
 * MemoryAuditLog vitest (Plan 7B Task 4) — 4 项.
 *
 * loading / audit empty / audit 列表 / active 模式一键否决 (POST 调用).
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/memoryApi'
import MemoryAuditLog from '@/components/memory/MemoryAuditLog'
import type { AuditEdge, MemoryEdge, MemoryNode } from '@/types/memory'

vi.mock('@/api/memoryApi')

const mkAudit = (overrides: Partial<AuditEdge> = {}): AuditEdge => ({
  edge_id: 'e1',
  rel_type: 'HOLDS',
  source_label: '我',
  target_label: '茅台',
  invalidated_at: '2025-09-01T00:00:00Z',
  invalidated_by_edge_id: null,
  original_reasoning: '用户更正',
  ...overrides,
})

const mkMemoryEdge = (overrides: Partial<MemoryEdge> = {}): MemoryEdge => ({
  edge_id: 'e_active',
  source_node_id: 'n_user',
  target_node_id: 'n_stock',
  rel_type: 'HOLDS',
  valid_from: '2025-01-01',
  valid_to: null,
  importance: 0.9,
  reasoning: '重仓',
  ...overrides,
})

const userNode: MemoryNode = {
  node_id: 'n_user',
  entity_type: 'User',
  entity_label: '我',
  properties: {},
}
const stockNode: MemoryNode = {
  node_id: 'n_stock',
  entity_type: 'Stock',
  entity_label: '茅台',
  properties: {},
}

describe('<MemoryAuditLog>', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('renders Spin while loading', () => {
    vi.mocked(api.fetchMemoryAudit).mockReturnValue(new Promise(() => {}))
    render(<MemoryAuditLog />)
    expect(document.querySelector('.ant-spin')).not.toBeNull()
  })

  it("audit mode shows 'memory works fine' when no invalidated rows", async () => {
    vi.mocked(api.fetchMemoryAudit).mockResolvedValue({ items: [], total: 0 })
    render(<MemoryAuditLog />)
    await waitFor(() =>
      expect(screen.getByText(/暂无被纠正的记录/)).toBeTruthy(),
    )
  })

  it('audit mode lists invalidated edges with source / target labels', async () => {
    vi.mocked(api.fetchMemoryAudit).mockResolvedValue({
      items: [
        mkAudit({ edge_id: 'e1' }),
        mkAudit({ edge_id: 'e2', target_label: '五粮液' }),
      ],
      total: 2,
    })
    render(<MemoryAuditLog />)
    await waitFor(() => {
      // antd 把 source / rel tag / target 拆成多 inline span,
      // 所以用 textContent 方式匹配整个 cell 内容.
      expect(document.querySelector('[data-row-key="e1"]')).not.toBeNull()
      expect(document.querySelector('[data-row-key="e2"]')).not.toBeNull()
    })
    expect(document.body.textContent).toContain('茅台')
    expect(document.body.textContent).toContain('五粮液')
  })

  it('active mode + one-click invalidate calls invalidateMemoryEdge', async () => {
    vi.mocked(api.fetchMemoryAudit).mockResolvedValue({ items: [], total: 0 })
    vi.mocked(api.fetchMemoryGraph).mockResolvedValue({
      nodes: [userNode, stockNode],
      edges: [mkMemoryEdge({ edge_id: 'e_active' })],
    })
    vi.mocked(api.invalidateMemoryEdge).mockResolvedValue({
      edge_id: 'e_active',
      invalidated_at: '2026-05-11T00:00:00Z',
      status: 'invalidated',
    })

    const user = userEvent.setup()
    render(<MemoryAuditLog />)
    // wait for initial audit fetch to settle (empty -> ToggleBar 显示)
    await waitFor(() => screen.getByTestId('toggle-active'))
    // Toggle to active mode
    await user.click(screen.getByTestId('toggle-active'))

    await waitFor(() => screen.getByTestId('invalidate-btn-e_active'))

    // 一键否决 → 弹 Popconfirm → 点 OK
    await user.click(screen.getByTestId('invalidate-btn-e_active'))
    // antd v5 在中文按钮文本中插入空格 (CSS rendering),
    // findByRole({ name: /^否\s*决$/ }) 兼容 "否决" / "否 决"
    const okBtn = await screen.findByRole(
      'button',
      { name: /^否\s*决$/ },
      { timeout: 3000 },
    )
    await user.click(okBtn)

    await waitFor(() =>
      expect(api.invalidateMemoryEdge).toHaveBeenCalledWith('e_active'),
    )
  })
})
