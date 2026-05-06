/**
 * frontend/src/pages/research/Detail.tsx
 *
 * v0.9.x research detail page (/research/:id). Reads from store/report.ts.
 *
 * Status branches:
 *   - completed → ReportCanvas (long scroll + Anchor ToC)
 *   - streaming → live markdown render (driven by SSE) + progress overlay
 *   - failed    → empty / error
 *
 * Streaming wiring:
 *   On status='streaming', kick off `reportActions.startStreaming(id)`. The store
 *   maintains `streaming.partialSections.report_markdown` which we render inline.
 *   On `done` event, store re-fetches detail → status flips to 'completed' →
 *   ReportCanvas takes over and the overlay fades out.
 */

import { useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { Spin, Tag, Empty } from 'antd'
import { useSnapshot } from 'valtio'
import { marked } from 'marked'
import dayjs from 'dayjs'
import { reportState, reportActions } from '@/store/report'
import type { InvestmentDueDiligenceReport } from '@/types/research'
import ReportCanvas from '@/components/report-canvas'
import ProgressOverlay from '@/components/progress-overlay'
import styles from './Detail.module.scss'

const STATUS_COLOR: Record<string, string> = {
  completed: 'green',
  streaming: 'blue',
  failed: 'red',
}

const STATUS_LABEL: Record<string, string> = {
  completed: '完成',
  streaming: '进行中',
  failed: '失败',
}

export default function ResearchDetailPage() {
  const { id } = useParams<{ id: string }>()
  const snap = useSnapshot(reportState)
  const cancelStreamingRef = useRef<(() => void) | null>(null)

  // 进入页面拉取 detail;离开页面取消订阅 + 清理 current.
  useEffect(() => {
    if (id) void reportActions.fetchDetail(id)
    return () => {
      cancelStreamingRef.current?.()
      cancelStreamingRef.current = null
      reportActions.clearCurrent()
      reportActions.resetStreaming()
    }
  }, [id])

  // 状态变 streaming 时启动 SSE 订阅(仅启动一次).
  const status = snap.current?.status
  useEffect(() => {
    if (!id) return
    if (
      status === 'streaming' &&
      !snap.streaming.active &&
      cancelStreamingRef.current === null
    ) {
      cancelStreamingRef.current = reportActions.startStreaming(id)
    }
    // status 转出 streaming 时,顺手把 cancel ref 清掉(订阅已经自然结束).
    if (status !== 'streaming' && cancelStreamingRef.current && !snap.streaming.active) {
      cancelStreamingRef.current = null
    }
  }, [status, id, snap.streaming.active])

  if (snap.currentLoading && !snap.current) {
    return <Spin tip="加载研报..." className={styles.spin} />
  }

  if (!snap.current) {
    return <Empty description="未找到该研报" />
  }

  const r = snap.current

  return (
    <div className={styles.page}>
      <header className={styles.meta}>
        <h1 className={styles.title}>{r.target_name}</h1>
        <div className={styles.metaRow}>
          <Tag color={STATUS_COLOR[r.status] ?? 'default'}>
            {STATUS_LABEL[r.status] ?? r.status}
          </Tag>
          <span>创建于 {dayjs(r.created_at).format('YYYY-MM-DD HH:mm')}</span>
          <span>成本 ¥{r.cost.toFixed(2)}</span>
          {r.target_ts_code && (
            <span className={styles.tsCode}>{r.target_ts_code}</span>
          )}
        </div>
      </header>

      {r.status === 'streaming' ? (
        <StreamingBody />
      ) : (
        <ReportCanvas report={r.report_json as InvestmentDueDiligenceReport} />
      )}

      <ProgressOverlay />
    </div>
  )
}

/**
 * Streaming render:渲染 store 里累积的 partialSections.report_markdown.
 * Backend writer_node 每次 emit 完整 markdown — 我们直接覆盖 + re-render.
 */
function StreamingBody() {
  const snap = useSnapshot(reportState)
  const md =
    typeof snap.streaming.partialSections.report_markdown === 'string'
      ? snap.streaming.partialSections.report_markdown
      : ''

  if (!md) {
    return (
      <div className={styles.streamingPlaceholder}>
        <Spin tip="研究中,正在汇总..." />
      </div>
    )
  }

  return (
    <div className={styles.streamingCanvas}>
      <div
        className={styles.streamingMarkdown}
        dangerouslySetInnerHTML={{ __html: marked.parse(md) as string }}
      />
    </div>
  )
}
