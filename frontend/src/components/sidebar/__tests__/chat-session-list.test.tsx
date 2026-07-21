import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { useLocation } from 'react-router-dom'
import { renderWithProviders } from '@/test-utils/render'
import { server } from '@/test-utils/msw-server'
import { ChatSessionList } from '@/components/sidebar/chat-session-list'
import { chatSessionsActions } from '@/store/chat-sessions'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''
const now = '2026-05-09T00:00:00Z'
function Probe({ onLoc }: { onLoc: (path: string) => void }) {
  onLoc(useLocation().pathname)
  return null
}

describe('<ChatSessionList>', () => {
  beforeEach(() => chatSessionsActions.reset())

  it('lists v1 sessions by updated_at and navigates on click', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/tenants`, () => HttpResponse.json([
        { id: 'tenant-1', name: 'Personal', is_personal: true, role: 'owner' },
      ])),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/sessions`, () => HttpResponse.json([
        { id: 'a', tenant_id: 'tenant-1', created_by_user_id: 'u', title: 'old', created_at: now, updated_at: now, archived_at: null },
        { id: 'b', tenant_id: 'tenant-1', created_by_user_id: 'u', title: 'new', created_at: now, updated_at: '2026-05-09T01:00:00Z', archived_at: null },
      ])),
    )
    let path = ''
    const { findByText } = renderWithProviders(<><ChatSessionList /><Probe onLoc={(value) => { path = value }} /></>)
    const newItem = await findByText('new')
    fireEvent.click(newItem)
    await waitFor(() => expect(path).toBe('/chat/b'))
  })
})
