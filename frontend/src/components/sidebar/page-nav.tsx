import { Link } from 'react-router-dom'
import { Icon, type IconName } from '@/components/shared/Icon'
import styles from '@/styles/app-shell.module.scss'

const LINKS: { to: string; label: string; icon: IconName }[] = [
  { to: '/research', label: '研报中心', icon: 'document' },
  { to: '/reports', label: '报告中心', icon: 'document' },
  { to: '/portfolio', label: '持仓', icon: 'chart' },
  { to: '/monitoring', label: '监控告警', icon: 'bell' },
  { to: '/memory', label: '我的画像', icon: 'user-circle' },
  { to: '/knowledge', label: '知识库', icon: 'book' },
]

export function PageNav() {
  return (
    <nav
      className={styles.navList}
      data-testid="sidebar-page-nav"
    >
      {LINKS.map((l) => (
        <Link key={l.to} to={l.to} className={styles.navItem}>
          <Icon name={l.icon} size={18} />
          {l.label}
        </Link>
      ))}
    </nav>
  )
}
