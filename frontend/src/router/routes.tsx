import { AuthGuard } from '@/components/auth-guard'
import { BaseLayout } from '@/layout/base'
import { ThemedRoot } from '@/themes/themed-root'
import NotFound from '@/pages/404'
import LoginPage from '@/pages/auth/login'
import RegisterPage from '@/pages/auth/register'
import Index from '@/pages/index'
import KnowledgePage from '@/pages/knowledge'
import MonitoringIndex from '@/pages/monitoring'
import AlertDetail from '@/pages/monitoring/alert-detail'
import MonitoringConfig from '@/pages/monitoring/config'
import ResearchIndex from '@/pages/research/index'
import ResearchNew from '@/pages/research/new'
import ResearchReport from '@/pages/research/report'
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
  {
    path: '/',
    Component: Index,
  },
  {
    path: '/knowledge',
    Component: KnowledgePage,
  },
  {
    path: '/monitoring',
    Component: MonitoringIndex,
  },
  {
    path: '/monitoring/:cid/alert/:aid',
    Component: AlertDetail,
  },
  {
    path: '/monitoring/config',
    Component: MonitoringConfig,
  },
  {
    path: '/research',
    Component: ResearchIndex,
  },
  {
    path: '/research/new',
    Component: ResearchNew,
  },
  {
    path: '/research/:id',
    Component: ResearchReport,
  },
  {
    path: '/404',
    Component: NotFound,
    pure: true,
  },
]

export const router = createBrowserRouter(
  [
    {
      path: '/',
      Component: ThemedRoot,
      children: [
        {
          path: '/login',
          element: <LoginPage />,
        },
        {
          path: '/register',
          element: <RegisterPage />,
        },
        {
          path: '/',
          element: (
            <AuthGuard>
              <BaseLayout>
                <Outlet />
              </BaseLayout>
            </AuthGuard>
          ),
          children: routes,
        },
        {
          path: '*',
          element: <Navigate to="/404" />,
        },
      ],
    },
  ] as RouteObject[],
  {
    basename: import.meta.env.BASE_URL,
  },
)
