import { useEffect, useState } from 'react'
import type { ChatMessage, ToolCallData } from '@/types/chat'
import { Icon } from '@/components/shared/Icon'
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

/** SVG spinner icon (replaces antd LoadingOutlined, carries data-testid for tests). */
function SpinnerIcon() {
  return (
    <svg
      data-testid="tool-running-spinner"
      width={14}
      height={14}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      style={{ animation: 'spin 1s linear infinite' }}
    >
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
    </svg>
  )
}

/** Small close/X icon for error state (carries data-testid for tests). */
function ErrorIcon() {
  return (
    <svg
      data-testid="tool-error-icon"
      width={14}
      height={14}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <circle cx="8" cy="8" r="6" />
      <path d="M6 6l4 4M10 6l-4 4" />
    </svg>
  )
}

export function ToolCallCard({ message }: ToolCallCardProps) {
  const data = message.tool_call_data as unknown as ToolCallData | null
  const isError = data?.status === 'error'
  const [expanded, setExpanded] = useState(isError)

  useEffect(() => {
    if (isError) setExpanded(true)
  }, [isError])

  if (!data) return null

  const isRunning = data.status === 'running'

  const statusIcon = isError ? (
    <ErrorIcon />
  ) : isRunning ? (
    <SpinnerIcon />
  ) : (
    <Icon name="check" size={14} aria-hidden />
  )

  const duration = formatDuration(data.started_at, data.ended_at)

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
        <div className={styles.toolIcon}>
          <Icon name="tool" size={14} aria-hidden />
        </div>
        <span className={styles.toolCardName}>{data.tool_name}</span>
        <span className={styles.toolStatus}>
          <span className={styles.dot} />
          <span>{statusIcon}</span>
          {isError ? '失败' : isRunning ? '运行中' : '完成'}
        </span>
        {duration ? (
          <span className={styles.toolCardDuration}>{duration}</span>
        ) : null}
        <span className={styles.toolCardChevron}>
          <Icon name={expanded ? 'chevron-down' : 'chevron-right'} size={14} aria-hidden />
        </span>
      </button>
      {expanded ? (
        <div className={styles.toolCardBody}>
          <div className={styles.toolCardSection}>
            <strong>args:</strong>
            <pre>{JSON.stringify(data.tool_args, null, 2)}</pre>
          </div>
          {isError ? (
            <div className={styles.toolCardSection}>
              <strong>error:</strong>
              <pre>{data.error_message ?? '(unknown)'}</pre>
              <button type="button" className={styles.retryBtn} aria-label="重试">
                <Icon name="close" size={12} aria-hidden /> 重试
              </button>
            </div>
          ) : data.result_summary ? (
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
