import type { ReactNode } from 'react'
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
    </div>
  )
}

export default AppShell
