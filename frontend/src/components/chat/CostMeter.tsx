import { DollarOutlined, DownOutlined, RightOutlined } from '@ant-design/icons'
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
    <div className={styles.costMeter} data-testid="cost-meter">
      <DollarOutlined />
      <span className={styles.costTotal}>{fmt(total_usd)}</span>
      <button
        type="button"
        className={styles.costToggle}
        onClick={() => setOpen((v) => !v)}
        aria-label="详情"
      >
        {open ? <DownOutlined /> : <RightOutlined />}
      </button>
      {open ? (
        <div className={styles.costBreakdown}>
          <span>Chat: {fmt(chat_usd)}</span>
          <span>Research: {fmt(research_usd)}</span>
        </div>
      ) : null}
    </div>
  )
}
