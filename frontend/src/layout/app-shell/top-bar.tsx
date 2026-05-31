import { useSnapshot } from 'valtio'
import { useParams } from 'react-router-dom'
import { currentChatState } from '@/store/current-chat'
import { chatSessionsState } from '@/store/chat-sessions'
import { Icon } from '@/components/shared/Icon'
import styles from '@/styles/app-shell.module.scss'

interface TopBarProps {
  sidebarCollapsed: boolean
  onToggleSidebar: () => void
}

export function TopBar({ sidebarCollapsed, onToggleSidebar }: TopBarProps) {
  const params = useParams<{ session_id?: string }>()
  const sessionId = params.session_id
  const snap = useSnapshot(currentChatState)
  const sessionsSnap = useSnapshot(chatSessionsState)
  const session = sessionId
    ? sessionsSnap.sessions.find((s) => s.id === sessionId)
    : null
  const title = session?.title ?? 'AlphaScout'
  const msgCount = snap.messages?.length ?? 0
  const sub = sessionId ? `${msgCount} turns` : '通用金融 agent 平台'

  return (
    <div className={styles.topbar} data-testid="app-topbar">
      <button
        className={styles.iconBtn}
        aria-label={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
        title={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
        onClick={onToggleSidebar}
        data-testid="sidebar-toggle-btn"
      >
        <Icon name="panel-left" />
      </button>
      <div className={styles.topbarTitleWrap}>
        <div className={styles.topbarTitle}>{title}</div>
        <div className={styles.topbarSub}>{sub}</div>
      </div>
      <div className={styles.topbarActions}>
        <button className={styles.iconBtn} aria-label="导出" title="导出">
          <Icon name="export" />
        </button>
        <a className={styles.iconBtn} aria-label="我的画像" title="我的画像" href="/memory#persona">
          <Icon name="user-circle" />
        </a>
      </div>
    </div>
  )
}
