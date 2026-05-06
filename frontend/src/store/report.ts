/**
 * frontend/src/store/report.ts
 *
 * Valtio store for v0.9.x research reports.
 * Sub-state: list (paginated) / current (detail) / streaming (SSE progress).
 *
 * SSE startStreaming subscription is intentionally NOT in this Task 11; it lands
 * in Task 14 once the展示页 needs live progress wiring. Here we only expose the
 * state shape so consumers can already read/write streaming.* without compile errors.
 */

import { proxy } from 'valtio'
import * as reportsApi from '@/api/reports'
import type { ReportDetail, ReportListItem } from '@/api/reports'

export type TimeFilter = 'today' | 'week' | 'month' | 'all'

export interface ProgressEvent {
  type:
    | 'plan'
    | 'data_progress'
    | 'insight'
    | 'report_chunk'
    | 'critic_score'
    | 'done'
    | 'error'
  message: string
  timestamp: number
  /** Original SSE event payload — preserved for debug / ad-hoc rendering. */
  raw?: Record<string, unknown>
}

interface ReportState {
  // 列表态
  list: ReportListItem[]
  listTotal: number
  listPage: number
  listPageSize: number
  listLoading: boolean
  timeFilter: TimeFilter

  // 详情态
  current: ReportDetail | null
  currentLoading: boolean

  // 流式态(streaming 模式 — Task 14 真订阅)
  streaming: {
    active: boolean
    progress: ProgressEvent[]
    partialSections: Record<string, unknown>
  }
}

export const reportState = proxy<ReportState>({
  list: [],
  listTotal: 0,
  listPage: 1,
  listPageSize: 20,
  listLoading: false,
  timeFilter: 'all',
  current: null,
  currentLoading: false,
  streaming: {
    active: false,
    progress: [],
    partialSections: {},
  },
})

export const reportActions = {
  async fetchList(page = 1, pageSize = 20) {
    reportState.listLoading = true
    try {
      const res = await reportsApi.listReports(page, pageSize)
      reportState.list = res.data.items
      reportState.listTotal = res.data.total
      reportState.listPage = res.data.page
      reportState.listPageSize = res.data.page_size
      return res.data
    } finally {
      reportState.listLoading = false
    }
  },

  async fetchDetail(id: string) {
    reportState.currentLoading = true
    try {
      const res = await reportsApi.getReport(id)
      reportState.current = res.data
      return res.data
    } finally {
      reportState.currentLoading = false
    }
  },

  async deleteReport(id: string) {
    await reportsApi.deleteReport(id)
    reportState.list = reportState.list.filter((r) => r.id !== id)
    reportState.listTotal = Math.max(0, reportState.listTotal - 1)
    if (reportState.current?.id === id) {
      reportState.current = null
    }
  },

  async startReport(targetName: string, tsCode?: string, researchStyle?: string) {
    const res = await reportsApi.startReport({
      target_name: targetName,
      target_ts_code: tsCode,
      research_style: researchStyle,
    })
    return res.data.id
  },

  setTimeFilter(filter: TimeFilter) {
    reportState.timeFilter = filter
  },

  clearCurrent() {
    reportState.current = null
  },

  resetStreaming() {
    reportState.streaming.active = false
    reportState.streaming.progress = []
    reportState.streaming.partialSections = {}
  },

  // startStreaming(id) — SSE EventSource subscription lands in Task 14
}

export type { ReportDetail, ReportListItem }
