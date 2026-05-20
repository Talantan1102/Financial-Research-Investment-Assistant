import { useSnapshot } from 'valtio'
import { authState } from '@/store/auth'
import { Icon } from '@/components/shared/Icon'
import styles from '@/styles/app-shell.module.scss'

export function UserPanel() {
  const snap = useSnapshot(authState)
  const name = snap.isLoggedIn && snap.user ? snap.user.username : 'anonymous'
  const initial = name.charAt(0).toUpperCase()
  return (
    <div
      data-testid="sidebar-user-panel"
      className={styles.userRow}
    >
      <div className={styles.userAvatar}>{initial}</div>
      <div className={styles.userInfo}>
        <div className={styles.userName}>{name}</div>
        <div className={styles.userRole}>Tier 1 · Analyst</div>
      </div>
      <Icon name="chevron-right" size={14} className={styles.userChev} />
    </div>
  )
}
