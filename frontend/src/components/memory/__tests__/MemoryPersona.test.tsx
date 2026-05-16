import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '@/api/personaApi'
import MemoryPersona from '@/components/memory/MemoryPersona'

vi.mock('@/api/personaApi')

const mkItem = (overrides: Partial<api.PersonaItem> = {}): api.PersonaItem => ({
  id: `id-${Math.random()}`,
  text: '默认',
  source: 'user',
  position: 0,
  created_at: '2026-05-17T00:00:00+00:00',
  updated_at: '2026-05-17T00:00:00+00:00',
  ...overrides,
})

describe('<MemoryPersona>', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('renders Spin while loading', () => {
    vi.mocked(api.fetchPersona).mockReturnValue(new Promise(() => {}))
    render(<MemoryPersona />)
    expect(document.querySelector('.ant-spin')).not.toBeNull()
  })

  it('renders two sections with items', async () => {
    vi.mocked(api.fetchPersona).mockResolvedValue({
      user_declared: [mkItem({ text: '保守稳健', source: 'user' })],
      agent_inferred: [mkItem({ text: '关注新能源', source: 'agent' })],
    })

    render(<MemoryPersona />)

    await waitFor(() => {
      expect(screen.getByText('保守稳健')).toBeTruthy()
      expect(screen.getByText('关注新能源')).toBeTruthy()
    })
    expect(screen.getByText('你声明的')).toBeTruthy()
    expect(screen.getByText('agent 观察到的')).toBeTruthy()
  })

  it('shows empty state when both sections empty', async () => {
    vi.mocked(api.fetchPersona).mockResolvedValue({
      user_declared: [],
      agent_inferred: [],
    })

    render(<MemoryPersona />)

    await waitFor(() => {
      expect(screen.getByText(/还没有任何记忆/)).toBeTruthy()
    })
  })

  it('shows section-level placeholder when one section empty', async () => {
    vi.mocked(api.fetchPersona).mockResolvedValue({
      user_declared: [mkItem({ text: '保守稳健' })],
      agent_inferred: [],
    })

    render(<MemoryPersona />)

    await waitFor(() => {
      expect(screen.getByText('保守稳健')).toBeTruthy()
      expect(screen.getByText('（暂无）')).toBeTruthy()
    })
  })

  it('shows error state when fetch fails', async () => {
    vi.mocked(api.fetchPersona).mockRejectedValue(new Error('boom'))
    render(<MemoryPersona />)
    await waitFor(() => {
      expect(screen.getByText(/加载失败/)).toBeTruthy()
    })
  })
})
