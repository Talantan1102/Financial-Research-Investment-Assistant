import { Fragment, memo, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ChatMessage } from '@/types/chat'
import { renderMarkdownWithCharts } from '@/utils/markdown'
import { ChartSpecRenderer } from './ChartSpecRenderer'
import chatStyles from '@/styles/chat.module.scss'
import markdownStyles from '@/styles/markdown.module.scss'

export interface TextMessageProps {
  message: ChatMessage
}

/**
 * `[查看](#mem-{edge_id})` anchor pattern (C.5 Plan 7B Task 6).
 *
 * Agent 在回复中显式提及 memory 来源时插此 link, 前端拦截点击 → 跳
 * `/memory?highlight_edge={edge_id}` (MemoryGraph 高亮该 edge).
 *
 * 普通 anchor (`#section1`) / 普通 http link 不被拦截.
 */
const MEM_LINK_HREF = /^#mem-([A-Za-z0-9_-]+)$/

function TextMessageInner({ message }: TextMessageProps) {
  const navigate = useNavigate()
  const isUser = message.role === 'user'
  const isAssistant = message.role === 'assistant'

  const { html, charts } = useMemo(
    () => renderMarkdownWithCharts(message.content),
    [message.content],
  )
  const parts = html.split(/(<div data-chart-spec-id="chart-\d+"><\/div>)/g)

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      // Bubble up: find nearest <a>
      let el: HTMLElement | null = e.target as HTMLElement
      while (el && el !== e.currentTarget && el.tagName !== 'A') {
        el = el.parentElement
      }
      if (!el || el.tagName !== 'A') return
      const href = (el as HTMLAnchorElement).getAttribute('href') ?? ''
      const m = href.match(MEM_LINK_HREF)
      if (m) {
        e.preventDefault()
        navigate(`/memory?highlight_edge=${encodeURIComponent(m[1])}`)
      }
    },
    [navigate],
  )

  const content = (
    <div
      data-role={message.role}
      data-testid={`text-msg-${message.id}`}
      className={`${markdownStyles.markdownBody} ${isUser ? markdownStyles.user : markdownStyles.assistant}`}
      onClick={handleClick}
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

  if (isUser) {
    return (
      <div className={chatStyles.rowUser} data-testid={`msg-user-${message.id}`}>
        <div className={chatStyles.bubbleUser}>{content}</div>
      </div>
    )
  }
  if (isAssistant) {
    return (
      <div className={chatStyles.rowAi} data-testid={`msg-ai-${message.id}`}>
        <div className={chatStyles.aiMeta}>
          <span className={chatStyles.aiBadge}>Analyst</span>
        </div>
        <div className={chatStyles.bubbleAi}>{content}</div>
      </div>
    )
  }
  return content
}

export const TextMessage = memo(
  TextMessageInner,
  (a, b) =>
    a.message.content === b.message.content && a.message.role === b.message.role,
)
