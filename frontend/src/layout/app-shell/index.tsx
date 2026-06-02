import { useState } from 'react'
import type { ReactNode } from 'react'
import MemoryOnboardingModal from '@/components/memory/MemoryOnboardingModal'
import { Sidebar } from './sidebar'
import { TopBar } from './top-bar'
import './index.scss'

const SIDEBAR_KEY = 'sidebar:collapsed'

function readSidebarCollapsed(): boolean {
  try { return localStorage.getItem(SIDEBAR_KEY) === '1' } catch { return false }
}

interface AppShellProps {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsed)

  function toggleSidebar() {
    setSidebarCollapsed((prev) => {
      const next = !prev
      try { localStorage.setItem(SIDEBAR_KEY, next ? '1' : '0') } catch { /* ignore */ }
      return next
    })
  }

  return (
    <div className={`app-shell${sidebarCollapsed ? ' app-shell--sidebar-collapsed' : ''}`}>
      <div className="app-shell__top-bar" data-testid="app-shell-top-bar">
        <TopBar sidebarCollapsed={sidebarCollapsed} onToggleSidebar={toggleSidebar} />
      </div>
      <div className="app-shell__sidebar" data-testid="app-shell-sidebar">
        <Sidebar />
      </div>
      <div className="app-shell__main" data-testid="app-shell-main">
        {children}
      </div>
      {/* C.5 Plan 7B Task 5 — first-session onboarding (#8 算法深度补丁 b).
          AppShell 是 AuthGuard 之内的容器, 仅登录态用户挂载本 modal;
          内部用 localStorage 标记不重弹. */}
      <MemoryOnboardingModal />
    </div>
  )
}

export default AppShell
