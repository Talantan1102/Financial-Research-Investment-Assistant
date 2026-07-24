import type {
  PaperAccount,
  PaperHolding,
  PaperOrder,
  PaperOrderStatus,
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

async function readJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...authHeaders(),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: string | { message?: string }
    } | null
    const detail = body?.detail
    throw new Error(
      typeof detail === 'string'
        ? detail
        : (detail?.message ?? `模拟账户读取失败（${response.status}）`),
    )
  }
  return response.json() as Promise<T>
}

export function getPaperAccount(): Promise<PaperAccount> {
  return readJson('/api/v0/paper-trading/account')
}

export function listPaperHoldings(
  filters: { account_generation?: number } = {},
): Promise<PaperHolding[]> {
  const query = new URLSearchParams()
  if (filters.account_generation !== undefined) {
    query.set('account_generation', String(filters.account_generation))
  }
  const suffix = query.size > 0 ? `?${query.toString()}` : ''
  return readJson(`/api/v0/paper-trading/holdings${suffix}`)
}

export function listPaperOrders(
  filters: {
    account_generation?: number
    status?: PaperOrderStatus
    ts_code?: string
    limit?: number
    offset?: number
  } = {},
): Promise<PaperOrder[]> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined) query.set(key, String(value))
  }
  const suffix = query.size > 0 ? `?${query.toString()}` : ''
  return readJson(`/api/v0/paper-trading/orders${suffix}`)
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
