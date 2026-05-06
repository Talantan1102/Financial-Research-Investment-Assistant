import IconHome from '@/assets/layout/home.svg'
import IconKnowledge from '@/assets/layout/knowledge.svg'
import IconMonitoring from '@/assets/layout/monitoring.svg'
import IconResearch from '@/assets/layout/policy.svg'
import { useMemo } from 'react'
import { useLocation } from 'react-router-dom'
import { NavItem } from './nav-item'
import './nav.scss'

export function Nav() {
  const { pathname } = useLocation()

  const items = useMemo(
    () => [
      {
        key: 'home',
        label: '首页',
        icon: IconHome,
        href: '/',
      },
      {
        key: 'research',
        label: '研究历史',
        icon: IconResearch,
        href: '/research',
      },
      {
        key: 'knowledge',
        label: '知识库',
        icon: IconKnowledge,
        href: '/knowledge',
      },
      {
        key: 'monitoring',
        label: '持仓预警',
        icon: IconMonitoring,
        href: '/monitoring',
      },
    ],
    [],
  )

  return (
    <div className="base-layout-nav">
      {items.map(({ key, onClick, ...item }) => (
        <NavItem
          key={key}
          {...item}
          active={pathname === item.href}
          onClick={onClick}
        />
      ))}
    </div>
  )
}
