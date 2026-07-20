/** Compatibility-shaped client for chat UI actions backed by Run APIs. */
import type { EscalationPacket } from '@/types/escalation'
import { getAuthToken } from './auth-token'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''
const apiUrl = (path: string) => `${API_BASE.replace(/\/$/, '')}${path}`
const authHeaders = (): Record<string, string> => {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export interface ConfirmEscalationArgs {
  tenant_id?: string
  session_id: string
  packet: EscalationPacket
}

export interface ConfirmEscalationResult {
  ok: true
  record_id?: string
}

/** Submit a confirmed escalation through the tenant-scoped Run control plane. */
export async function confirmEscalation(
  args: ConfirmEscalationArgs,
): Promise<ConfirmEscalationResult> {
  if (!args.tenant_id) throw new Error('tenant_id is required for escalation')
  const response = await fetch(
    apiUrl(`/api/v1/tenants/${encodeURIComponent(args.tenant_id)}/research-escalations`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({
        source_session_id: args.session_id,
        packet_confirmed: args.packet,
        user_edits: [],
      }),
    },
  )
  if (!response.ok) throw new Error(`escalation failed: ${response.status}`)
  return { ok: true }
}

export type { EscalationPacket }
