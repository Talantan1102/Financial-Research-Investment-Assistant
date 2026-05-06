/**
 * 认证插件:
 * - request: 自动加 Token
 * - response: 401 时清 localStorage auth + 跳 /login
 */
import { IRequestPlugin } from './plugin'

const AUTH_STORAGE_KEY = 'auth'

function getToken(): string | null {
  try {
    const authData = localStorage.getItem(AUTH_STORAGE_KEY)
    if (authData) {
      const parsed = JSON.parse(authData)
      return parsed?.token || null
    }
  } catch {
    // ignore
  }
  return null
}

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
        const token = getToken()
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
        // token 失效 / 未登录 → 清 auth + 跳 /login
        if (error?.response?.status === 401) {
          clearAuthAndRedirect()
        }
        return Promise.reject(error)
      }
    )
  },
}
