import type { IconName } from '@/components/shared/Icon'

export interface NavLink { to: string; label: string; icon: IconName }

export const NAV_LINKS: NavLink[] = [
  { to: '/research', label: '研究中心', icon: 'document' },
  { to: '/reports', label: '报告中心', icon: 'document' },
  { to: '/portfolio', label: '持仓', icon: 'chart' },
  { to: '/portfolio-overview', label: '持仓总览', icon: 'chart' },
  { to: '/paper-trading', label: '模拟账户', icon: 'chart' },
  { to: '/monitoring', label: '监控告警', icon: 'bell' },
  { to: '/memory', label: '我的画像', icon: 'user-circle' },
  { to: '/knowledge', label: '知识库', icon: 'book' },
]
