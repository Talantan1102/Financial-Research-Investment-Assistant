import { useState } from 'react'
import { useSnapshot } from 'valtio'
import { currentChatState } from '@/store/current-chat'
import styles from '@/styles/chat.module.scss'

export function CostMeter() {
  const [open, setOpen] = useState(false)
  const snap = useSnapshot(currentChatState)
  // Bug chat-send-04: cost_breakdown.total_usd is never updated (the cost_update
  // reducer only writes cost_so_far). Read cost_so_far directly as the primary
  // "已耗" total so it updates whenever a cost_update SSE event arrives.
  const totalUsd = snap.cost_so_far
  const { chat_usd, research_usd } = snap.cost_breakdown ?? {
    chat_usd: 0,
    research_usd: 0,
  }
  const fmt = (n: number) => `$${n.toFixed(n < 0.01 ? 4 : 3)}`
  return (
    <div className={styles.costStrip} data-testid="cost-meter">
      <span className={styles.costPill}>
        <span className={styles.dot} />
        已耗 <span className={styles.v}>{fmt(totalUsd)}</span>
      </span>
      {open && (
        <>
          <span className={styles.costPill}>
            Chat: <span className={styles.v}>{fmt(chat_usd)}</span>
          </span>
          <span className={styles.costPill}>
            Research: <span className={styles.v}>{fmt(research_usd)}</span>
          </span>
        </>
      )}
      <button
        type="button"
        className={styles.costToggle}
        onClick={() => setOpen((v) => !v)}
        aria-label="详情"
      >
        {open ? '▲' : '▼'}
      </button>
    </div>
  )
}
