import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Popover, Divider } from 'antd'
import { useSnapshot } from 'valtio'
import { authState, authActions } from '@/store/auth'
import { Icon } from '@/components/shared/Icon'
import { NAV_LINKS } from '@/components/sidebar/nav-links'
import styles from '@/styles/app-shell.module.scss'

function PopoverContent({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()

  function handleLogout() {
    onClose()
    authActions.logout()
    navigate('/login')
  }

  return (
    <div className={styles.userPopoverContent}>
      {NAV_LINKS.map((l) => (
        <Link
          key={l.to}
          to={l.to}
          className={styles.userPopoverItem}
          onClick={onClose}
        >
          <Icon name={l.icon} size={16} />
          <span>{l.label}</span>
        </Link>
      ))}
      <Divider style={{ margin: '6px 0' }} />
      <button
        type="button"
        className={styles.userPopoverItem}
        onClick={handleLogout}
      >
        <Icon name="log-out" size={16} />
        <span>退出登录</span>
      </button>
    </div>
  )
}

export function UserPanel() {
  const snap = useSnapshot(authState)
  const name = snap.isLoggedIn && snap.user ? snap.user.username : 'anonymous'
  const initial = name.charAt(0).toUpperCase()
  const [open, setOpen] = useState(false)

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      placement="topRight"
      arrow={false}
      content={<PopoverContent onClose={() => setOpen(false)} />}
      overlayInnerStyle={{ padding: 6, borderRadius: 12 }}
    >
      <div
        data-testid="sidebar-user-panel"
        className={styles.userRow}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setOpen((v) => !v) }}
      >
        <div className={styles.userAvatar}>{initial}</div>
        <div className={styles.userInfo}>
          <div className={styles.userName}>{name}</div>
          <div className={styles.userRole}>Tier 1 · Analyst</div>
        </div>
        <Icon name="chevron-up" size={14} className={styles.userChev} />
      </div>
    </Popover>
  )
}
