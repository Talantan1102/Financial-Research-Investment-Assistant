import { AuthGuard } from '@/components/auth-guard'
import { AppShell } from '@/layout/app-shell'
import { ThemedRoot } from '@/themes/themed-root'
import NotFound from '@/pages/404'
import LoginPage from '@/pages/auth/login'
import RegisterPage from '@/pages/auth/register'
import ChatLandingPage from '@/pages/chat/landing'
import ChatSessionPage from '@/pages/chat/session'
import KnowledgePage from '@/pages/knowledge'
import MemoryPage from '@/pages/memory'
import MonitoringIndex from '@/pages/monitoring'
import AlertDetail from '@/pages/monitoring/alert-detail'
import MonitoringConfig from '@/pages/monitoring/config'
import PortfolioPage from '@/pages/portfolio'
import PortfolioOverviewPage from '@/pages/portfolio-overview'
import PaperTradingPage from '@/pages/paper-trading'
import WatchlistPage from '@/pages/watchlist'
import ReportsListPage from '@/pages/reports'
import ResearchDetailPage from '@/pages/research/Detail'
import ResearchListPage from '@/pages/research/List'
import ResearchNew from '@/pages/research/new'
import {
  Navigate,
  Outlet,
  RouteObject,
  createBrowserRouter,
} from 'react-router-dom'

export type IRouteObject = {
  children?: IRouteObject[]
  name?: string
  auth?: boolean
  pure?: boolean
  meta?: any
} & Omit<RouteObject, 'children'>

export const routes: IRouteObject[] = [
  { path: '/', element: <Navigate to="/chat" replace /> },
  { path: '/chat', Component: ChatLandingPage },
  { path: '/chat/:session_id', Component: ChatSessionPage },
  { path: '/reports', Component: ReportsListPage },
  { path: '/research', Component: ResearchListPage },
  { path: '/research/new', Component: ResearchNew },
  { path: '/research/:id', Component: ResearchDetailPage },
  { path: '/portfolio', Component: PortfolioPage },
  { path: '/portfolio-overview', Component: PortfolioOverviewPage },
  { path: '/paper-trading', Component: PaperTradingPage },
  { path: '/watchlist', Component: WatchlistPage },
  { path: '/knowledge', Component: KnowledgePage },
  { path: '/monitoring', Component: MonitoringIndex },
  { path: '/monitoring/:cid/alert/:aid', Component: AlertDetail },
  { path: '/monitoring/config', Component: MonitoringConfig },
  { path: '/memory', Component: MemoryPage },
  { path: '/404', Component: NotFound, pure: true },
]

export const router = createBrowserRouter(
  [
    {
      path: '/',
      Component: ThemedRoot,
      children: [
        { path: '/login', element: <LoginPage /> },
        { path: '/register', element: <RegisterPage /> },
        {
          path: '/',
          element: (
            <AuthGuard>
              <AppShell>
                <Outlet />
              </AppShell>
            </AuthGuard>
          ),
          children: routes,
        },
        { path: '*', element: <Navigate to="/404" /> },
      ],
    },
  ] as RouteObject[],
  { basename: import.meta.env.BASE_URL },
)
