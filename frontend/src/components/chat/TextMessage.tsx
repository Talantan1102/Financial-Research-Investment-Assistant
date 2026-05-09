import { Fragment, memo, useMemo } from 'react'
import type { ChatMessage } from '@/types/chat'
import { renderMarkdownWithCharts } from '@/utils/markdown'
import { ChartSpecRenderer } from './ChartSpecRenderer'
import styles from '@/styles/markdown.module.scss'

export interface TextMessageProps {
  message: ChatMessage
}

function TextMessageInner({ message }: TextMessageProps) {
  const { html, charts } = useMemo(
    () => renderMarkdownWithCharts(message.content),
    [message.content],
  )
  const parts = html.split(/(<div data-chart-spec-id="chart-\d+"><\/div>)/g)
  return (
    <div
      data-role={message.role}
      data-testid={`text-msg-${message.id}`}
      className={`${styles.markdownBody} ${message.role === 'user' ? styles.user : styles.assistant}`}
    >
      {parts.map((p, idx) => {
        const m = p.match(/data-chart-spec-id="(chart-\d+)"/)
        if (m) {
          const found = charts.find((c) => c.id === m[1])
          return found ? <ChartSpecRenderer key={idx} spec={found.spec} /> : null
        }
        return (
          <Fragment key={idx}>
            <span dangerouslySetInnerHTML={{ __html: p }} />
          </Fragment>
        )
      })}
    </div>
  )
}

export const TextMessage = memo(
  TextMessageInner,
  (a, b) =>
    a.message.content === b.message.content && a.message.role === b.message.role,
)
