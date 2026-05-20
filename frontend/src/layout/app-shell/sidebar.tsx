import { useState } from 'react'
import { ChatSessionList } from '@/components/sidebar/chat-session-list'
import { NewChatButton } from '@/components/sidebar/new-chat-button'
import { PageNav } from '@/components/sidebar/page-nav'
import { UserPanel } from '@/components/sidebar/user-panel'
import { Icon } from '@/components/shared/Icon'
import styles from '@/styles/app-shell.module.scss'

export function Sidebar() {
  const [query, setQuery] = useState('')

  return (
    <div className={styles.sidebar} data-testid="app-sidebar">
      <div className={styles.brandRow}>
        <div className={styles.brandMark}>α</div>
        <div className={styles.brandName}>AlphaScout</div>
      </div>

      <label className={styles.searchBox}>
        <Icon name="search" />
        <input
          placeholder="搜索对话..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          data-testid="sidebar-search-input"
        />
      </label>

      <NewChatButton />

      <div className={styles.sessionsScroll}>
        <ChatSessionList query={query} />
      </div>

      <PageNav />
      <UserPanel />
    </div>
  )
}
