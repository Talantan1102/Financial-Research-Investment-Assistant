import { Button } from 'antd'
import { useNavigate } from 'react-router-dom'
import { chatSessionsActions } from '@/store/chat-sessions'

export function NewChatButton() {
  const navigate = useNavigate()
  async function handleClick() {
    const created = await chatSessionsActions.createAndAdd()
    navigate(`/chat/${created.id}`)
  }
  return (
    <Button
      type="primary"
      block
      data-testid="sidebar-new-chat-button"
      onClick={handleClick}
    >
      + New Chat
    </Button>
  )
}
