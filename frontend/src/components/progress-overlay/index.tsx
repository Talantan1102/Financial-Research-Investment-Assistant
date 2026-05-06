/**
 * frontend/src/components/progress-overlay/index.tsx
 *
 * Global sticky progress overlay (bottom-right) — 渲染 store 全局 streaming state.
 * 跨页存活(BaseLayout 嵌入),user 切走再切回 progress 不丢.
 * 点击 header → 跳到正在 stream 的 detail 页.
 */

import { Timeline } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useSnapshot } from 'valtio'
import { reportState } from '@/store/report'
import styles from './index.module.scss'

const TIMELINE_LIMIT = 10

export default function ProgressOverlay() {
  const snap = useSnapshot(reportState)
  const navigate = useNavigate()

  // 不显示:既不 streaming 也没 progress 历史(避免空 panel)
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

  const targetId = snap.streaming.currentId
  const handleClick = () => {
    if (targetId) navigate(`/research/${targetId}`)
  }

  return (
    <div
      className={`${styles.overlay} ${
        snap.streaming.active ? styles.visible : styles.fadeOut
      }`}
      role="status"
      aria-live="polite"
    >
      <h3
        className={styles.heading}
        onClick={handleClick}
        style={targetId ? { cursor: 'pointer' } : undefined}
        title={targetId ? '点击查看研报详情' : undefined}
      >
        {snap.streaming.active ? '研究进行中' : '研究已完成'}
        {targetId && <span className={styles.headingHint}> →</span>}
      </h3>
      <Timeline items={items} />
    </div>
  )
}
