/**
 * frontend/src/store/report.ts
 *
 * Valtio store for v0.9.x research reports.
 * Sub-state: list (paginated) / current (detail) / streaming (SSE progress).
 *
 * Task 14: startStreaming subscribes to GET /reports/:id/stream via fetch +
 * ReadableStream (instead of EventSource) so we can attach `Authorization:
 * Bearer <token>` — EventSource API does not support custom request headers.
 * This is the same pattern used by GitHub Copilot / OpenAI SDK for LLM streams.
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

  // 流式态 — 全局(不绑 component lifecycle):
  // user 切走再切回 detail 页,SSE 仍在跑,progress overlay 持续显示。
  streaming: {
    active: boolean
    /** 正在 stream 的 report id;null 表示无活跃 stream. */
    currentId: string | null
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
    currentId: null,
    progress: [],
    partialSections: {},
  },
})

// AbortController 不放 valtio proxy(class instance 不被 deep proxy 但保险起见放 module-level)
let _streamController: AbortController | null = null

// ── helpers ─────────────────────────────────────────────────────────────────

const AUTH_STORAGE_KEY = 'auth'

function readAuthToken(): string | null {
  try {
    const stored = localStorage.getItem(AUTH_STORAGE_KEY)
    if (!stored) return null
    const parsed = JSON.parse(stored) as { token?: string | null }
    return parsed.token ?? null
  } catch {
    return null
  }
}

function streamUrl(reportId: string): string {
  // Match api/research.ts apiUrl() — VITE_API_BASE is the prefix Vite proxies.
  const base = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
  return `${base.replace(/\/$/, '')}/reports/${reportId}/stream`
}

const PROGRESS_LABELS: Record<string, string> = {
  plan: '正在制定研究计划',
  data_progress: '收集数据中',
  insight: '分析洞察',
  report_chunk: '撰写章节',
  critic_score: '内部审核',
  done: '研报完成',
  error: '出错了',
}

function extractMessage(
  eventType: string,
  eventData: Record<string, unknown> | string | null | undefined,
): string {
  // Backend _adapt_event 在 v0.9.x 几乎所有 event 都带 data.summary;直接用之.
  if (typeof eventData === 'string') return eventData
  if (eventData && typeof eventData === 'object') {
    const summary = (eventData as Record<string, unknown>).summary
    if (typeof summary === 'string' && summary.length > 0) return summary
    const message = (eventData as Record<string, unknown>).message
    if (typeof message === 'string' && message.length > 0) return message
  }
  return PROGRESS_LABELS[eventType] ?? eventType
}

// ── actions ─────────────────────────────────────────────────────────────────

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
    reportState.streaming.currentId = null
    reportState.streaming.progress = []
    reportState.streaming.partialSections = {}
  },

  /** 用户登出 / 全局取消 streaming */
  cancelStreaming() {
    _streamController?.abort()
    _streamController = null
    reportState.streaming.active = false
    reportState.streaming.currentId = null
  },

  /**
   * Subscribe to GET /reports/:id/stream (SSE).
   *
   * Implementation: fetch + ReadableStream (NOT EventSource) so we can attach
   * `Authorization: Bearer <token>` — EventSource has no header API. This is
   * the canonical pattern used by GitHub Copilot / OpenAI SDK / Anthropic SDK.
   *
   * Returns a `cancel` function the caller should invoke on unmount.
   */
  /**
   * 启动 SSE 全局订阅 — 不绑 component lifecycle.
   *
   * - 已经在 stream 同 id → no-op(组件 re-mount 不重启 SSE,progress 不丢)
   * - 已经在 stream 别的 id → abort 旧的 + 启动新的
   * - 不返 cancel function(显式 cancel 用 cancelStreaming)
   */
  startStreaming(reportId: string): void {
    // 同 id 已在跑 → no-op(避免组件 re-mount 重置 progress)
    if (
      reportState.streaming.active &&
      reportState.streaming.currentId === reportId
    ) {
      return
    }

    // 切到新 id → abort 旧 stream
    if (_streamController) {
      _streamController.abort()
      _streamController = null
    }

    reportState.streaming.active = true
    reportState.streaming.currentId = reportId
    reportState.streaming.progress = []
    reportState.streaming.partialSections = {}

    const controller = new AbortController()
    _streamController = controller
    const token = readAuthToken()

    void (async () => {
      try {
        const response = await fetch(streamUrl(reportId), {
          method: 'GET',
          headers: {
            Accept: 'text/event-stream',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          signal: controller.signal,
        })

        if (!response.ok) {
          throw new Error(`SSE fetch failed: ${response.status}`)
        }
        if (!response.body) {
          throw new Error('SSE response has no body')
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        // SSE 帧分隔符 = '\n\n';单帧 'data: <json>'.
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const parts = buffer.split('\n\n')
          buffer = parts.pop() ?? ''

          for (const part of parts) {
            const line = part.trim()
            if (!line.startsWith('data:')) continue
            const json = line.slice('data:'.length).trim()
            if (!json) continue

            let event: { type?: string; data?: unknown }
            try {
              event = JSON.parse(json) as { type?: string; data?: unknown }
            } catch {
              continue
            }

            const eventType = event.type ?? 'unknown'
            const eventData = (event.data ?? {}) as
              | Record<string, unknown>
              | string

            reportState.streaming.progress.push({
              type: eventType as ProgressEvent['type'],
              message: extractMessage(eventType, eventData),
              timestamp: Date.now(),
              raw: event as Record<string, unknown>,
            })

            // Accumulate partial output for streaming render.
            if (eventType === 'report_chunk' && typeof eventData === 'object') {
              const chunk = (eventData as Record<string, unknown>).chunk
              if (typeof chunk === 'string') {
                reportState.streaming.partialSections.report_markdown = chunk
              }
            } else if (
              eventType === 'critic_score' &&
              typeof eventData === 'object'
            ) {
              const ed = eventData as Record<string, unknown>
              if (ed.scorer === 'aggregate') {
                if (ed.scores)
                  reportState.streaming.partialSections.critic_scores = ed.scores
                if (typeof ed.overall === 'number')
                  reportState.streaming.partialSections.critic_overall = ed.overall
              }
            }

            if (eventType === 'done') {
              reportState.streaming.active = false
              // re-fetch detail 拿后端写回的最终 report_json
              try {
                await reportActions.fetchDetail(reportId)
              } catch (e) {
                console.error('fetchDetail after done failed:', e)
              }
              return
            }

            if (eventType === 'error') {
              reportState.streaming.active = false
              return
            }
          }
        }

        // 流自然结束但没收到 done — 也视为完成,re-fetch detail.
        if (reportState.streaming.active) {
          reportState.streaming.active = false
          try {
            await reportActions.fetchDetail(reportId)
          } catch {
            /* noop */
          }
        }
      } catch (e) {
        if ((e as Error).name === 'AbortError') return
        reportState.streaming.active = false
        reportState.streaming.progress.push({
          type: 'error',
          message: `连接错误:${(e as Error).message}`,
          timestamp: Date.now(),
        })
      } finally {
        // 该 stream 结束(done / error / 自然结束):清 controller ref
        if (_streamController === controller) {
          _streamController = null
        }
      }
    })()
  },
}

export type { ReportDetail, ReportListItem }
