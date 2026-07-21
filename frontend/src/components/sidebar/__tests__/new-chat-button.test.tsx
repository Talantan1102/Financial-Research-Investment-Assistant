import { describe, expect, it } from 'vitest'
import { fireEvent } from '@testing-library/react'
import { useLocation } from 'react-router-dom'
import { renderWithProviders } from '@/test-utils/render'
import { NewChatButton } from '@/components/sidebar/new-chat-button'
import { currentChatActions, currentChatState } from '@/store/current-chat'

function LocationProbe({ onLoc }: { onLoc: (path: string) => void }) {
  onLoc(useLocation().pathname)
  return null
}

describe('<NewChatButton>', () => {
  it('resets the draft and navigates to lazy /chat without precreating a session', () => {
    currentChatActions.adoptRunSession('old')
    let pathname = ''
    const { getByTestId } = renderWithProviders(
      <><NewChatButton /><LocationProbe onLoc={(path) => { pathname = path }} /></>,
      { initialRoute: '/chat/old' },
    )
    fireEvent.click(getByTestId('sidebar-new-chat-button'))
    expect(pathname).toBe('/chat')
    expect(currentChatState.session_id).toBeNull()
  })
})
