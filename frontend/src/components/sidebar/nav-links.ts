import type { IconName } from '@/components/shared/Icon'

export interface NavLink {
  to: string
  label: string
  icon: IconName
}

export const NAV_LINKS: NavLink[] = [
  { to: '/research',   label: '研报中心', icon: 'document'    },
  { to: '/reports',    label: '报告中心', icon: 'document'    },
  { to: '/portfolio',  label: '持仓',     icon: 'chart'       },
  { to: '/monitoring', label: '监控告警', icon: 'bell'        },
  { to: '/memory',     label: '我的画像', icon: 'user-circle' },
  { to: '/knowledge',  label: '知识库',   icon: 'book'        },
]
