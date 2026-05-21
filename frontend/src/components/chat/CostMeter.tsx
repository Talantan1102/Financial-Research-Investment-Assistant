import { useState } from 'react'
import { useSnapshot } from 'valtio'
import { currentChatState } from '@/store/current-chat'
import styles from '@/styles/chat.module.scss'

export function CostMeter() {
  const [open, setOpen] = useState(false)
  const snap = useSnapshot(currentChatState)
  const { chat_usd, research_usd, total_usd } = snap.cost_breakdown ?? {
    chat_usd: 0,
    research_usd: 0,
    total_usd: 0,
  }
  const fmt = (n: number) => `$${n.toFixed(n < 0.01 ? 4 : 3)}`
  return (
    <div className={styles.costStrip} data-testid="cost-meter">
      <span className={styles.costPill}>
        <span className={styles.dot} />
        已耗 <span className={styles.v}>{fmt(total_usd)}</span>
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
