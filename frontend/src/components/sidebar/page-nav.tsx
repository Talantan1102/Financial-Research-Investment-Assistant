import { Link } from 'react-router-dom'

const LINKS = [
  { to: '/research', label: 'Research' },
  { to: '/reports', label: 'Reports' },
  { to: '/portfolio', label: 'Portfolio' },
  { to: '/monitoring', label: 'Monitoring' },
  { to: '/memory', label: 'Memory' },
  { to: '/knowledge', label: 'Knowledge' },
]

export function PageNav() {
  return (
    <nav
      data-testid="sidebar-page-nav"
      style={{ display: 'flex', flexDirection: 'column', gap: 4 }}
    >
      {LINKS.map((l) => (
        <Link key={l.to} to={l.to}>
          {l.label}
        </Link>
      ))}
    </nav>
  )
}
