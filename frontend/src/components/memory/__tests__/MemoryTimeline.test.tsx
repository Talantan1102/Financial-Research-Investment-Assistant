/**
 * MemoryTimeline vitest (Plan 7B Task 3) — 4 项.
 *
 * loading / empty / 数据态 bar 渲染 / entity 关键字筛.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/memoryApi'
import MemoryTimeline from '@/components/memory/MemoryTimeline'
import type { TimelineEdge } from '@/types/memory'

vi.mock('@/api/memoryApi')

const mkEdge = (overrides: Partial<TimelineEdge> = {}): TimelineEdge => ({
  edge_id: 'e1',
  rel_type: 'HOLDS',
  source_label: '我',
  target_label: '茅台',
  valid_from: '2025-01-01',
  valid_to: null,
  importance: 0.9,
  invalidated_at: null,
  ...overrides,
})

describe('<MemoryTimeline>', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('renders Spin while loading', () => {
    vi.mocked(api.fetchMemoryTimeline).mockReturnValue(new Promise(() => {}))
    render(<MemoryTimeline />)
    expect(document.querySelector('.ant-spin')).not.toBeNull()
  })

  it('renders Empty when no edges', async () => {
    vi.mocked(api.fetchMemoryTimeline).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 50,
    })
    render(<MemoryTimeline />)
    await waitFor(() =>
      expect(screen.getByText(/还没有时间序列/)).toBeTruthy(),
    )
  })

  it('renders one bar per edge', async () => {
    vi.mocked(api.fetchMemoryTimeline).mockResolvedValue({
      items: [
        mkEdge({ edge_id: 'e1' }),
        mkEdge({ edge_id: 'e2', rel_type: 'SOLD' }),
      ],
      total: 2,
      page: 1,
      page_size: 50,
    })
    render(<MemoryTimeline />)
    await waitFor(() => {
      expect(screen.getByTestId('timeline-bar-e1')).toBeTruthy()
      expect(screen.getByTestId('timeline-bar-e2')).toBeTruthy()
    })
  })

  it('filters bars by entity keyword', async () => {
    vi.mocked(api.fetchMemoryTimeline).mockResolvedValue({
      items: [
        mkEdge({ edge_id: 'e1', target_label: '茅台' }),
        mkEdge({ edge_id: 'e2', target_label: '五粮液' }),
      ],
      total: 2,
      page: 1,
      page_size: 50,
    })
    render(<MemoryTimeline />)
    await waitFor(() => screen.getByTestId('timeline-bar-e1'))

    const input = screen.getByPlaceholderText(/按实体名筛/)
    fireEvent.change(input, { target: { value: '茅台' } })

    await waitFor(() => {
      expect(screen.queryByTestId('timeline-bar-e1')).toBeTruthy()
      expect(screen.queryByTestId('timeline-bar-e2')).toBeNull()
    })
  })
})
