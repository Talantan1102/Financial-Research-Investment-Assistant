import { Link } from 'react-router-dom'
import { Icon } from '@/components/shared/Icon'
import { NAV_LINKS } from '@/components/sidebar/nav-links'
import styles from '@/styles/app-shell.module.scss'

export function PageNav() {
  return (
    <nav
      className={styles.navList}
      data-testid="sidebar-page-nav"
    >
      {NAV_LINKS.map((l) => (
        <Link key={l.to} to={l.to} className={styles.navItem}>
          <Icon name={l.icon} size={18} />
          {l.label}
        </Link>
      ))}
    </nav>
  )
}
