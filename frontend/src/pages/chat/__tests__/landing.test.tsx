import { describe, expect, it, vi } from 'vitest'
import { useLocation } from 'react-router-dom'
import { renderWithProviders } from '@/test-utils/render'
import ChatLandingPage from '@/pages/chat/landing'

vi.mock('@/hooks/useRunSSE', () => ({
  useRunSSE: () => ({ sendPrompt: vi.fn(), cancelRun: vi.fn(), resumeRun: vi.fn(),
    resubmitPrompt: vi.fn(), abort: vi.fn(), status: 'idle', activeRunId: null }),
}))
vi.mock('@/store/chat-sessions', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/store/chat-sessions')>()
  return { ...actual, chatSessionsActions: { ...actual.chatSessionsActions, resolveTenantId: vi.fn(async () => 'tenant-1') } }
})

function Probe({ onLoc }: { onLoc: (path: string) => void }) {
  onLoc(useLocation().pathname)
  return null
}

describe('<ChatLandingPage>', () => {
  it('keeps a lazy session on /chat until the first Run adopts an id', () => {
    let path = ''
    renderWithProviders(<><ChatLandingPage /><Probe onLoc={(value) => { path = value }} /></>, { initialRoute: '/chat' })
    expect(path).toBe('/chat')
  })
})
