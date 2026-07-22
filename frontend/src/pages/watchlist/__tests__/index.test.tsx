import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import WatchlistPage from '@/pages/watchlist'

vi.mock('@/api/watchlist', () => ({ listWatchlist: vi.fn().mockResolvedValue([{ id: '1', ts_code: '600000.SH', name: '浦发银行', note: null, monitoring_enabled: false }]), addWatchlist: vi.fn(), updateWatchlist: vi.fn(), removeWatchlist: vi.fn() }))

describe('WatchlistPage', () => {
  it('renders editable watchlist and monitoring switch', async () => {
    render(<WatchlistPage />)
    expect(await screen.findByDisplayValue('浦发银行')).toBeInTheDocument()
    expect(screen.getByRole('switch')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '删除' })).toBeInTheDocument()
  })
})
