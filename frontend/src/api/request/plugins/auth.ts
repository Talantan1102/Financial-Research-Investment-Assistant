/**
 * 认证插件:
 * - request: 自动加 Token
 * - response: 401 时清 localStorage auth + 跳 /login
 *   例外: login/register 自身的 401 不清 token(让页面自己 catch 显示错误)
 */
import { getAuthToken, AUTH_STORAGE_KEY } from '../../auth-token' // C67: import SSOT key
import { IRequestPlugin } from './plugin'

// 这些 endpoint 的 401 属于"密码错误",不应清掉已登录用户的 token
const AUTH_NO_CLEAR_PATHS = ['/auth/login', '/auth/register']

function clearAuthAndRedirect(): void {
  // 清 localStorage 让下次进 AuthGuard 时 isLoggedIn=false
  localStorage.removeItem(AUTH_STORAGE_KEY)
  // 已经在 /login 或 /register 不再跳
  const path = window.location.pathname
  if (path !== '/login' && path !== '/register') {
    // 用 location.href 强制 reload — 简单稳妥(plugin 层没 react-router context)
    window.location.href = '/login'
  }
}

export const authPlugin: IRequestPlugin = {
  preinstall(instance) {
    instance.interceptors.request.use(
      (config) => {
        const token = getAuthToken()
        if (token) {
          config.headers.Authorization = `Bearer ${token}`
        }
        return config
      },
      (error) => Promise.reject(error)
    )

    instance.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error?.response?.status === 401) {
          const reqUrl: string = (error?.config?.url as string) ?? ''
          if (AUTH_NO_CLEAR_PATHS.some((p) => reqUrl.includes(p))) {
            // 登录/注册接口的 401 = 凭证错误,让调用方自己处理
            return Promise.reject(error)
          }
          // 其他 401 = token 失效 / 未登录 → 清 auth + 跳 /login
          clearAuthAndRedirect()
        }
        return Promise.reject(error)
      }
    )
  },
}
