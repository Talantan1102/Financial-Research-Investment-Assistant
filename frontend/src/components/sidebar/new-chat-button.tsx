import { useNavigate } from 'react-router-dom'
import { currentChatActions } from '@/store/current-chat'
import { Icon } from '@/components/shared/Icon'
import styles from '@/styles/app-shell.module.scss'

export function NewChatButton() {
  const navigate = useNavigate()
  function handleClick() {
    currentChatActions.reset()
    navigate('/chat')
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
