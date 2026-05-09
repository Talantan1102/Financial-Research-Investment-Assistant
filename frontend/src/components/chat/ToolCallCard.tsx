import { CheckCircleFilled, DownOutlined, LoadingOutlined, RightOutlined } from '@ant-design/icons'
import { useState } from 'react'
import type { ChatMessage, ToolCallData } from '@/types/chat'
import styles from '@/styles/chat.module.scss'

export interface ToolCallCardProps {
  message: ChatMessage
}

function formatDuration(start: string, end?: string): string {
  if (!end) return ''
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (ms < 1000) return `${ms}ms`
  return `${Math.round(ms / 1000)}s`
}

export function ToolCallCard({ message }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false)
  const data = message.tool_call_data as unknown as ToolCallData | null
  if (!data) return null
  const isRunning = data.status === 'running'
  const isError = data.status === 'error'
  return (
    <div
      className={`${styles.toolCard} ${isError ? styles.toolCardError : ''}`}
      data-state={data.status}
      data-testid={`tool-card-${message.id}`}
    >
      <button
        type="button"
        className={styles.toolCardHeader}
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-label={expanded ? 'collapse' : '展开'}
      >
        <span className={styles.toolCardIcon}>
          {isRunning ? (
            <LoadingOutlined data-testid="tool-running-spinner" />
          ) : (
            <CheckCircleFilled />
          )}
        </span>
        <span className={styles.toolCardName}>{data.tool_name}</span>
        <span className={styles.toolCardDuration}>
          {formatDuration(data.started_at, data.ended_at)}
        </span>
        <span className={styles.toolCardChevron}>
          {expanded ? <DownOutlined /> : <RightOutlined />}
        </span>
      </button>
      {expanded ? (
        <div className={styles.toolCardBody}>
          <div className={styles.toolCardSection}>
            <strong>args:</strong>
            <pre>{JSON.stringify(data.tool_args, null, 2)}</pre>
          </div>
          {data.result_summary ? (
            <div className={styles.toolCardSection}>
              <strong>result:</strong>
              <pre>{data.result_summary}</pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
