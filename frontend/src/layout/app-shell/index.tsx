import type { ReactNode } from 'react'
import MemoryOnboardingModal from '@/components/memory/MemoryOnboardingModal'
import { Sidebar } from './sidebar'
import { TopBar } from './top-bar'
import './index.scss'

interface AppShellProps {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="app-shell">
      <div className="app-shell__top-bar" data-testid="app-shell-top-bar">
        <TopBar />
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
