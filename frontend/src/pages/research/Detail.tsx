/**
 * frontend/src/pages/research/Detail.tsx
 *
 * v0.9.x research detail page (/research/:id).
 * Reads from store/report.ts (Task 11). Status branches:
 *   - completed → ReportCanvas (long scroll + Anchor ToC)  ← THIS TASK
 *   - streaming → placeholder (Task 14 wires SSE UI)
 *   - failed    → empty / error
 */

import { useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { Spin, Tag, Empty } from 'antd'
import { useSnapshot } from 'valtio'
import dayjs from 'dayjs'
import { reportState, reportActions } from '@/store/report'
import type { InvestmentDueDiligenceReport } from '@/types/research'
import ReportCanvas from '@/components/report-canvas'
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

  useEffect(() => {
    if (id) void reportActions.fetchDetail(id)
    return () => {
      // 离页清理 current(避免下次进 detail 闪现旧数据)
      reportActions.clearCurrent()
    }
  }, [id])

  if (snap.currentLoading) {
    return <Spin tip="加载研报..." className={styles.spin} />
  }

  if (!snap.current) {
    return <Empty description="未找到该研报" />
  }

  const r = snap.current

  if (r.status === 'streaming') {
    // Task 14 实现 streaming 分支;本 task 占位
    return (
      <div className={styles.page}>
        <header className={styles.meta}>
          <h1 className={styles.title}>{r.target_name}</h1>
          <div className={styles.metaRow}>
            <Tag color={STATUS_COLOR[r.status]}>{STATUS_LABEL[r.status]}</Tag>
            <span>研报生成中(streaming UI 由 Task 14 实现)</span>
          </div>
        </header>
        <Empty description="研报正在生成,请稍后刷新" />
      </div>
    )
  }

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
      <ReportCanvas
        report={r.report_json as InvestmentDueDiligenceReport}
      />
    </div>
  )
}
