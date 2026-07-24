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

export interface PaperOrderPreviewOptions {
  fetchImpl?: typeof fetch
  signal?: AbortSignal
}

function normalizePreviewOptions(
  value: typeof fetch | PaperOrderPreviewOptions | undefined,
): PaperOrderPreviewOptions {
  if (value === undefined) return {}
  if (typeof value === 'function') return { fetchImpl: value }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(
      'paper preview options must be a fetch function or options object',
    )
  }
  const unknownKeys = Object.keys(value).filter(
    (key) => key !== 'fetchImpl' && key !== 'signal',
  )
  if (unknownKeys.length > 0) {
    throw new TypeError(`unknown paper preview option: ${unknownKeys[0]}`)
  }
  if (value.fetchImpl !== undefined && typeof value.fetchImpl !== 'function') {
    throw new TypeError('paper preview fetchImpl must be a function')
  }
  if (value.signal !== undefined && !(value.signal instanceof AbortSignal)) {
    throw new TypeError('paper preview signal must be an AbortSignal')
  }
  return value
}

export function previewPaperOrder(
  payload: PaperOrderPreviewRequest,
  fetchImpl?: typeof fetch,
): Promise<PaperOrderPreview>
export function previewPaperOrder(
  payload: PaperOrderPreviewRequest,
  options?: PaperOrderPreviewOptions,
): Promise<PaperOrderPreview>
export async function previewPaperOrder(
  payload: PaperOrderPreviewRequest,
  fetchOrOptions?: typeof fetch | PaperOrderPreviewOptions,
): Promise<PaperOrderPreview> {
  const options = normalizePreviewOptions(fetchOrOptions)
  const fetchImpl = options.fetchImpl ?? fetch
  const response = await fetchImpl(
    `${API_BASE}/api/v0/paper-trading/orders/preview`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(),
      },
      body: JSON.stringify(payload),
      signal: options.signal,
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
