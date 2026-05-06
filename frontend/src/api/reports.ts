/**
 * frontend/src/api/reports.ts
 *
 * Client for the v0.9.x /reports CRUD endpoints (Task 8 + 9 backend).
 * Vite proxies /api → backend, axios baseURL = VITE_API_BASE.
 *
 * Endpoints (router prefix = "/reports" on backend):
 *   GET    /reports?page=&page_size=  → ReportListResponse
 *   GET    /reports/:id               → ReportDetail
 *   DELETE /reports/:id               → 204
 *   POST   /reports                   → { id }
 *   GET    /reports/:id/stream        → SSE (consumed in store/report.ts Task 14)
 */

import { request } from './request'
import type { InvestmentDueDiligenceReport } from '@/types/research'

export type ReportStatus = 'streaming' | 'completed' | 'failed'

export interface ReportListItem {
  id: string
  target_name: string
  target_ts_code: string | null
  status: ReportStatus
  cost: number
  created_at: string
  /** Extracted from report_json.investment_recommendation.recommendation; null while streaming. */
  investment_recommendation: string | null
}

export interface ReportListResponse {
  items: ReportListItem[]
  total: number
  page: number
  page_size: number
}

export interface ReportDetail {
  id: string
  target_name: string
  target_ts_code: string | null
  status: ReportStatus
  cost: number
  created_at: string
  updated_at: string
  request_id: string | null
  /** Empty object while streaming; full InvestmentDueDiligenceReport when completed. */
  report_json: InvestmentDueDiligenceReport | Record<string, unknown>
}

export interface ReportStartRequest {
  target_name: string
  target_ts_code?: string
  research_style?: string
}

export interface ReportStartResponse {
  id: string
}

/**
 * GET /reports — paginated list of current user's reports (newest first).
 */
export function listReports(page = 1, page_size = 20) {
  return request.get<ReportListResponse>('/reports', {
    params: { page, page_size },
    loading: false,
  })
}

/**
 * GET /reports/:id — full report detail with report_json.
 */
export function getReport(id: string) {
  return request.get<ReportDetail>(`/reports/${id}`, { loading: false })
}

/**
 * DELETE /reports/:id — 204 No Content.
 */
export function deleteReport(id: string) {
  return request.delete(`/reports/${id}`)
}

/**
 * POST /reports — create placeholder row (status='streaming') and return id.
 * Caller should immediately subscribe to /reports/:id/stream (SSE) for progress.
 */
export function startReport(payload: ReportStartRequest) {
  return request.post<ReportStartResponse>('/reports', payload)
}
