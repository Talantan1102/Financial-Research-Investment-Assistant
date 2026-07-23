import type {
  PaperOrderPreview,
  PaperOrderPreviewRequest,
} from '@/types/paper-trading'
import { getAuthToken } from './auth-token'

const API_BASE = ((import.meta.env.VITE_API_BASE as string) ?? '').replace(
  /\/$/,
  '',
)

function authHeaders(): Record<string, string> {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function previewPaperOrder(
  payload: PaperOrderPreviewRequest,
  fetchImpl: typeof fetch = fetch,
): Promise<PaperOrderPreview> {
  const response = await fetchImpl(
    `${API_BASE}/api/v0/paper-trading/orders/preview`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(),
      },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: string | { message?: string }
    } | null
    const detail = body?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : (detail?.message ?? `交易预览失败（${response.status}）`)
    throw new Error(message)
  }
  return response.json() as Promise<PaperOrderPreview>
}
