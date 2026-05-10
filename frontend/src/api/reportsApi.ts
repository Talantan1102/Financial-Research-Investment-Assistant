export interface ResearchReportSummary {
  id: string
  title: string
  source_chat_session_id: string | null
  created_at: string
  cost_usd: number
}

export interface ResearchReportDetail extends ResearchReportSummary {
  content_md: string
  metadata: Record<string, unknown>
}

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''

function apiUrl(path: string): string {
  const base = (API_BASE ?? '').replace(/\/$/, '')
  return `${base}${path}`
}

export async function listReports(params?: {
  source_chat_session_id?: string
  limit?: number
}): Promise<ResearchReportSummary[]> {
  const url = new URL(apiUrl('/api/v0/reports'), 'http://localhost')
  if (params?.source_chat_session_id) {
    url.searchParams.set('source_chat_session_id', params.source_chat_session_id)
  }
  if (params?.limit !== undefined) {
    url.searchParams.set('limit', String(params.limit))
  }
  const path = url.pathname + url.search
  const res = await fetch(apiUrl(path))
  if (!res.ok) throw new Error(`listReports failed: ${res.status}`)
  const json = (await res.json()) as { items: ResearchReportSummary[] } | ResearchReportSummary[]
  return Array.isArray(json) ? json : json.items
}

export async function getReport(id: string): Promise<ResearchReportDetail> {
  const res = await fetch(apiUrl(`/api/v0/reports/${encodeURIComponent(id)}`))
  if (!res.ok) throw new Error(`getReport failed: ${res.status}`)
  return res.json() as Promise<ResearchReportDetail>
}
