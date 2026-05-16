import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

describe('<MemoryPersona> interactions', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('add item via modal calls addPersonaItem with target_section=user', async () => {
    vi.mocked(api.fetchPersona).mockResolvedValueOnce({
      user_declared: [],
      agent_inferred: [],
    })
    vi.mocked(api.addPersonaItem).mockResolvedValue(
      mkItem({ text: '新条', source: 'user' })
    )
    vi.mocked(api.fetchPersona).mockResolvedValueOnce({
      user_declared: [mkItem({ text: '新条', source: 'user' })],
      agent_inferred: [],
    })

    render(<MemoryPersona />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /添加我的第一条/ })).toBeTruthy()
    })

    await userEvent.click(screen.getByRole('button', { name: /添加我的第一条/ }))
    const textarea = await screen.findByPlaceholderText(/输入一条画像/)
    await userEvent.type(textarea, '新条')
    await userEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))

    await waitFor(() => {
      expect(api.addPersonaItem).toHaveBeenCalledWith({
        text: '新条',
        target_section: 'user',
      })
    })
  })

  it('inline edit calls updatePersonaItem', async () => {
    const item = mkItem({ text: '原文', source: 'user', id: 'fixed-id' })
    vi.mocked(api.fetchPersona).mockResolvedValueOnce({
      user_declared: [item],
      agent_inferred: [],
    })
    vi.mocked(api.updatePersonaItem).mockResolvedValue({ ...item, text: '改后' })

    render(<MemoryPersona />)

    await waitFor(() => expect(screen.getByText('原文')).toBeTruthy())
    fireEvent.click(screen.getByTestId('persona-edit-fixed-id'))
    const textarea = await screen.findByDisplayValue('原文')
    fireEvent.change(textarea, { target: { value: '改后' } })
    fireEvent.click(screen.getByTestId('persona-save-fixed-id'))

    await waitFor(() => {
      expect(api.updatePersonaItem).toHaveBeenCalledWith('fixed-id', '改后')
    })
  })

  it('delete confirmation calls deletePersonaItem', async () => {
    const item = mkItem({ text: '待删', source: 'user', id: 'del-id' })
    vi.mocked(api.fetchPersona).mockResolvedValueOnce({
      user_declared: [item],
      agent_inferred: [],
    })
    vi.mocked(api.deletePersonaItem).mockResolvedValue()

    render(<MemoryPersona />)

    await waitFor(() => expect(screen.getByText('待删')).toBeTruthy())
    fireEvent.click(screen.getByTestId('persona-delete-del-id'))
    fireEvent.click(await screen.findByRole('button', { name: /^确\s*认$/ }))

    await waitFor(() => {
      expect(api.deletePersonaItem).toHaveBeenCalledWith('del-id')
    })
  })
})
