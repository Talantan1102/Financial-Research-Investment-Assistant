import { useState } from 'react'
import { ChatSessionList } from '@/components/sidebar/chat-session-list'
import { NewChatButton } from '@/components/sidebar/new-chat-button'
import { UserPanel } from '@/components/sidebar/user-panel'
import { Icon } from '@/components/shared/Icon'
import styles from '@/styles/app-shell.module.scss'

const HISTORY_KEY = 'sidebar:historyCollapsed'

function readCollapsed(): boolean {
  try { return localStorage.getItem(HISTORY_KEY) === '1' } catch { return false }
}

export function Sidebar() {
  const [query, setQuery] = useState('')
  const [historyCollapsed, setHistoryCollapsed] = useState(readCollapsed)

  function toggleHistory() {
    setHistoryCollapsed((prev) => {
      const next = !prev
      try { localStorage.setItem(HISTORY_KEY, next ? '1' : '0') } catch { /* ignore */ }
      return next
    })
  }

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

      <div className={styles.historyHeader}>
        <span className={styles.historyLabel}>对话历史</span>
        <button
          type="button"
          className={styles.historyCollapseBtn}
          onClick={toggleHistory}
          aria-label={historyCollapsed ? '展开对话历史' : '折叠对话历史'}
          aria-expanded={!historyCollapsed}
          data-testid="sidebar-history-toggle"
        >
          <Icon name={historyCollapsed ? 'chevron-right' : 'chevron-down'} size={14} />
        </button>
      </div>

      {!historyCollapsed && (
        <div className={styles.sessionsScroll}>
          <ChatSessionList query={query} />
        </div>
      )}

      <UserPanel />
    </div>
  )
}
