import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { VariableSizeList, type ListChildComponentProps } from 'react-window'
import { useScrollStick } from './useScrollStick'
import type { ChatMessage } from '@/types/chat'
import { ResearchReportCard } from './ResearchReportCard'
import { SystemMessage } from './SystemMessage'
import { TextMessage } from './TextMessage'
import { ToolCallCard } from './ToolCallCard'

export interface MessageListProps {
  messages: readonly ChatMessage[]
  height?: number
  onContinueAsk?: (messageId: string) => void
  // Plan 3 Task 7: error/partial assistant message 后显「重试」按钮,onClick 调
  // ChatPane.sse.retryTask(task_id) → backend POST /chat/retry/{tid} 从 checkpoint 续跑。
  onRetry?: (taskId: string) => void
}

const ESTIMATE_ROW_HEIGHT = 120

function MessageRouter({
  message,
  onContinueAsk,
  onRetry,
}: {
  message: ChatMessage
  onContinueAsk?: (id: string) => void
  onRetry?: (taskId: string) => void
}) {
  const main = (() => {
    switch (message.message_type) {
      case 'tool_call':
        return <ToolCallCard message={message} />
      case 'research_report':
        return <ResearchReportCard message={message} onContinueAsk={onContinueAsk} />
      case 'system':
        return <SystemMessage message={message} />
      case 'text':
      default:
        return <TextMessage message={message} />
    }
  })()

  // Plan 3 Task 7: assistant + (error|partial) + task_id 非空 → 显「重试」按钮
  const canRetry =
    message.role === 'assistant' &&
    (message.status === 'error' || message.status === 'partial') &&
    !!message.task_id &&
    !!onRetry
  return (
    <>
      {main}
      {canRetry ? (
        <button
          type="button"
          data-testid="retry-button"
          onClick={() => onRetry!(message.task_id!)}
          style={{
            marginTop: 8,
            padding: '4px 12px',
            border: '1px solid #d9d9d9',
            borderRadius: 4,
            background: '#fff',
            cursor: 'pointer',
          }}
        >
          重试
        </button>
      ) : null}
    </>
  )
}

type RowData = {
  messages: readonly ChatMessage[]
  onContinueAsk?: (messageId: string) => void
  onRetry?: (taskId: string) => void
}

const MemoRow = memo(function Row({
  index,
  style,
  data,
}: ListChildComponentProps<RowData>) {
  const m = data.messages[index]
  return (
    <div style={style} key={m.id}>
      <MessageRouter
        message={m}
        onContinueAsk={data.onContinueAsk}
        onRetry={data.onRetry}
      />
    </div>
  )
})

export function MessageList({
  messages,
  height = 600,
  onContinueAsk,
  onRetry,
}: MessageListProps) {
  const sizesRef = useRef<Map<number, number>>(new Map())
  const listRef = useRef<VariableSizeList<RowData>>(null)

  const itemSize = useCallback(
    (index: number) => sizesRef.current.get(index) ?? ESTIMATE_ROW_HEIGHT,
    [],
  )

  const itemKey = useCallback(
    (index: number, d: RowData) => d.messages[index].id,
    [],
  )

  const data = useMemo<RowData>(
    () => ({ messages, onContinueAsk, onRetry }),
    [messages, onContinueAsk, onRetry],
  )

  const [sentinelEl, setSentinelEl] = useState<HTMLDivElement | null>(null)
  const { isAtBottom, scrollToBottom } = useScrollStick(sentinelEl)
  const lastCount = useRef(messages.length)

  useEffect(() => {
    if (messages.length > lastCount.current && isAtBottom) {
      scrollToBottom()
    }
    lastCount.current = messages.length
  }, [messages.length, isAtBottom, scrollToBottom])

  return (
    <>
      <VariableSizeList
        ref={listRef}
        height={height}
        width="100%"
        itemCount={messages.length}
        itemSize={itemSize}
        itemKey={itemKey}
        itemData={data}
        overscanCount={4}
      >
        {MemoRow}
      </VariableSizeList>
      <div ref={setSentinelEl} data-testid="scroll-sentinel" style={{ height: 1 }} />
    </>
  )
}
