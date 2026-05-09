import { memo, useCallback, useMemo, useRef } from 'react'
import { VariableSizeList, type ListChildComponentProps } from 'react-window'
import type { ChatMessage } from '@/types/chat'
import { ResearchReportCard } from './ResearchReportCard'
import { SystemMessage } from './SystemMessage'
import { TextMessage } from './TextMessage'
import { ToolCallCard } from './ToolCallCard'

export interface MessageListProps {
  messages: readonly ChatMessage[]
  height?: number
  onContinueAsk?: (messageId: string) => void
}

const ESTIMATE_ROW_HEIGHT = 96

function MessageRouter({
  message,
  onContinueAsk,
}: {
  message: ChatMessage
  onContinueAsk?: (id: string) => void
}) {
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
}

type RowData = {
  messages: readonly ChatMessage[]
  onContinueAsk?: (messageId: string) => void
}

const MemoRow = memo(function Row({
  index,
  style,
  data,
}: ListChildComponentProps<RowData>) {
  const m = data.messages[index]
  return (
    <div style={style} key={m.id}>
      <MessageRouter message={m} onContinueAsk={data.onContinueAsk} />
    </div>
  )
})

export function MessageList({ messages, height = 600, onContinueAsk }: MessageListProps) {
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

  const data = useMemo<RowData>(() => ({ messages, onContinueAsk }), [messages, onContinueAsk])

  return (
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
  )
}
