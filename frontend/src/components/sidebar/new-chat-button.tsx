import { useNavigate } from 'react-router-dom'
import { chatSessionsActions } from '@/store/chat-sessions'
import { Icon } from '@/components/shared/Icon'
import styles from '@/styles/app-shell.module.scss'

export function NewChatButton() {
  const navigate = useNavigate()
  async function handleClick() {
    const session = await chatSessionsActions.getOrCreateEmptyChat()
    navigate(`/chat/${session.id}`)
  }
  return (
    <button
      type="button"
      className={styles.newChat}
      data-testid="sidebar-new-chat-button"
      onClick={handleClick}
    >
      <Icon name="plus" size={14} />
      新对话
      <span className={styles.newChatKbd}>⌘N</span>
    </button>
  )
}
