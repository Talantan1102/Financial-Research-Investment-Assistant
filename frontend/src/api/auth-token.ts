/**
 * Shared helper: read the bearer token from localStorage['auth'].
 * SSOT for all bare-fetch callers that cannot use the axios interceptor.
 */
const AUTH_STORAGE_KEY = 'auth'

export function getAuthToken(): string | null {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Record<string, unknown>
      return (parsed?.token as string) || null
    }
  } catch {
    // ignore parse errors
  }
  return null
}
