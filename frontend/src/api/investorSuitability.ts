import { getAuthToken } from './auth-token'

const API_BASE = ((import.meta.env.VITE_API_BASE as string) ?? '').replace(/\/$/, '')

export type Market = 'main' | 'chinext' | 'star' | 'bse'
export type EntitlementStatus =
  | 'not_applied'
  | 'pending_disclosure'
  | 'enabled'
  | 'restricted'
  | 'revoked'

export interface MarketEntitlement {
  entitlement_id: string
  market: Market
  status: EntitlementStatus
  can_buy: boolean
  can_sell: boolean
  can_subscribe: boolean
  rule_version: string | null
  enabled_at: string | null
  restricted_at: string | null
}

export interface EntitlementApplication {
  application_id: string
  market: Market
  status: string
  assessment_id: string | null
  started_at: string
  completed_at: string | null
}

export interface FailedCondition {
  code: 'assets_below_minimum' | 'experience_below_minimum'
  actual: string | number
  required: string | number
}

export interface SuitabilityAssessment {
  assessment_id: string
  market: Market
  decision: 'passed' | 'rejected'
  failed_conditions: FailedCondition[] | null
  rule_version: string
}

export interface ProfilePayload {
  declared_average_assets_20d: string
  securities_experience_months: number
  risk_level: string
}

function authHeaders(): Record<string, string> {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
        : (detail?.message ?? `权限服务暂时不可用（${response.status}）`),
    )
  }
  return response.json() as Promise<T>
}

export function getMarketPermissions(): Promise<MarketEntitlement[]> {
  return request('/api/v0/market-permissions')
}

export function startApplication(
  market: Market,
  idempotencyKey: string,
): Promise<EntitlementApplication> {
  return request(`/api/v0/market-permissions/${market}/applications`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ idempotency_key: idempotencyKey }),
  })
}

export function submitApplicationProfile(
  applicationId: string,
  payload: ProfilePayload,
): Promise<SuitabilityAssessment> {
  return request(`/api/v0/market-permissions/applications/${applicationId}/profile`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function confirmApplication(
  applicationId: string,
  disclosureVersion: string,
  idempotencyKey: string,
): Promise<MarketEntitlement> {
  return request(`/api/v0/market-permissions/applications/${applicationId}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      disclosure_version: disclosureVersion,
      idempotency_key: idempotencyKey,
    }),
  })
}

export function cancelApplication(
  applicationId: string,
): Promise<EntitlementApplication> {
  return request(`/api/v0/market-permissions/applications/${applicationId}/cancel`, {
    method: 'POST',
  })
}
