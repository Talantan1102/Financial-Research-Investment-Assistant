/**
 * frontend/src/components/progress-overlay/index.tsx
 *
 * Sticky progress overlay shown on the bottom-right corner during research
 * streaming. Renders an antd Timeline of recent SSE progress events
 * (research log) and fades out once `streaming.active === false`.
 *
 * State source: `reportState.streaming` — populated by
 * `reportActions.startStreaming` in store/report.ts.
 */

import { Timeline } from 'antd'
import { useSnapshot } from 'valtio'
import { reportState } from '@/store/report'
import styles from './index.module.scss'

const TIMELINE_LIMIT = 10

export default function ProgressOverlay() {
  const snap = useSnapshot(reportState)

  // 不显示:既不在 streaming, 也没有 progress 历史(避免空 panel)
  if (!snap.streaming.active && snap.streaming.progress.length === 0) {
    return null
  }

  const items = snap.streaming.progress
    .slice(-TIMELINE_LIMIT)
    .map((e, idx) => ({
      key: `${e.timestamp}-${idx}`,
      color:
        e.type === 'error'
          ? 'red'
          : e.type === 'done'
            ? 'green'
            : 'blue',
      children: e.message || e.type,
    }))

  return (
    <div
      className={`${styles.overlay} ${
        snap.streaming.active ? styles.visible : styles.fadeOut
      }`}
      role="status"
      aria-live="polite"
    >
      <h3 className={styles.heading}>
        {snap.streaming.active ? '研究进行中' : '研究已完成'}
      </h3>
      <Timeline items={items} />
    </div>
  )
}
