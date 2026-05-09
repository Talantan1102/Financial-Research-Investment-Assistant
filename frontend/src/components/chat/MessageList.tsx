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
}

const ESTIMATE_ROW_HEIGHT = 96

function MessageRouter({ message }: { message: ChatMessage }) {
  switch (message.message_type) {
    case 'tool_call':
      return <ToolCallCard message={message} />
    case 'research_report':
      return <ResearchReportCard message={message} />
    case 'system':
      return <SystemMessage message={message} />
    case 'text':
    default:
      return <TextMessage message={message} />
  }
}

type RowData = readonly ChatMessage[]

const MemoRow = memo(function Row({
  index,
  style,
  data,
}: ListChildComponentProps<RowData>) {
  const m = data[index]
  return (
    <div style={style} key={m.id}>
      <MessageRouter message={m} />
    </div>
  )
})

export function MessageList({ messages, height = 600 }: MessageListProps) {
  const sizesRef = useRef<Map<number, number>>(new Map())
  const listRef = useRef<VariableSizeList<RowData>>(null)

  const itemSize = useCallback(
    (index: number) => sizesRef.current.get(index) ?? ESTIMATE_ROW_HEIGHT,
    [],
  )

  const itemKey = useCallback(
    (index: number, data: RowData) => data[index].id,
    [],
  )

  const data = useMemo(() => messages, [messages])

  return (
    <VariableSizeList
      ref={listRef}
      height={height}
      width="100%"
      itemCount={data.length}
      itemSize={itemSize}
      itemKey={itemKey}
      itemData={data}
      overscanCount={4}
    >
      {MemoRow}
    </VariableSizeList>
  )
}
