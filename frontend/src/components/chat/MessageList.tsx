import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { VariableSizeList, type ListChildComponentProps } from 'react-window'
import { useScrollStick } from './useScrollStick'
import type { ChatMessage } from '@/types/chat'
import { ChartMessage } from './ChartMessage'
import { ResearchReportCard } from './ResearchReportCard'
import { SystemMessage } from './SystemMessage'
import { TextMessage } from './TextMessage'
import { ToolCallCard } from './ToolCallCard'

export interface MessageListProps {
  messages: readonly ChatMessage[]
  height?: number
  onContinueAsk?: (messageId: string) => void
}

const ESTIMATE_ROW_HEIGHT = 120

function MessageRouter({
  message,
  onContinueAsk,
}: {
  message: ChatMessage
  onContinueAsk?: (id: string) => void
}) {
  const main = (() => {
    switch (message.message_type) {
      case 'tool_call':
        return <ToolCallCard message={message} />
      case 'chart':
        return <ChartMessage message={message} />
      case 'research_report':
        return <ResearchReportCard message={message} onContinueAsk={onContinueAsk} />
      case 'system':
        return <SystemMessage message={message} />
      case 'text':
      default:
        return <TextMessage message={message} />
    }
  })()

  return (
    <>
      {main}
    </>
  )
}

type RowData = {
  messages: readonly ChatMessage[]
  onContinueAsk?: (messageId: string) => void
  // 把真实行高回填给 VariableSizeList。VariableSizeList 用 itemSize 算每行的绝对
  // top 定位,若高度估错(默认 120px)行与行会重叠。每行渲染后量自身高度上报。
  setSize: (index: number, size: number) => void
}

// 消息之间的纵向间距。react-window 的行是绝对定位的,flex 的 gap 不生效,所以这里
// 用 padding 在行内补出间距,并连同内容一起被测量。
const ROW_GAP = 14

const MemoRow = memo(function Row({
  index,
  style,
  data,
}: ListChildComponentProps<RowData>) {
  const m = data.messages[index]
  const innerRef = useRef<HTMLDivElement>(null)
  const { setSize } = data

  // 量真实高度回填给 VariableSizeList。用 ResizeObserver 而非 layout-effect:回调在
  // 浏览器完成布局后异步触发,既避开和 react-window 内部 metadata 重算在 commit 期
  // 的时序冲突(实测 layout-effect 版本只有最后一行生效),又能捕获字体/markdown/图表
  // 异步布局以及流式吐字带来的高度变化。
  useEffect(() => {
    const el = innerRef.current
    if (!el) return
    setSize(index, el.getBoundingClientRect().height)
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => {
      setSize(index, el.getBoundingClientRect().height)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [index, m.id, m.content, setSize])

  return (
    <div style={style} key={m.id}>
      <div ref={innerRef} style={{ paddingBottom: ROW_GAP }}>
        <MessageRouter
          message={m}
          onContinueAsk={data.onContinueAsk}
        />
      </div>
    </div>
  )
})

export function MessageList({
  messages,
  height = 600,
  onContinueAsk,
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

  const setSize = useCallback((index: number, size: number) => {
    if (sizesRef.current.get(index) === size) return
    sizesRef.current.set(index, size)
    // 高度变了,让 VariableSizeList 从该行起重算后续所有行的 top 定位。
    listRef.current?.resetAfterIndex(index)
  }, [])

  const data = useMemo<RowData>(
    () => ({ messages, onContinueAsk, setSize }),
    [messages, onContinueAsk, setSize],
  )

  const [sentinelEl, setSentinelEl] = useState<HTMLDivElement | null>(null)
  const { isAtBottom, scrollToBottom } = useScrollStick(sentinelEl)
  const lastCount = useRef(messages.length)

  // 跟随最后一条消息的内容,这样流式吐字(messages.length 不变、只是末条 content
  // 增长)时也能持续贴底。
  const lastMsg = messages[messages.length - 1]
  const lastContent = lastMsg?.content

  useEffect(() => {
    const grew = messages.length > lastCount.current
    // 用户刚发出的新消息,无论之前滚到哪都强制贴底(标准聊天行为:看到自己刚发的话);
    // AI 流式吐字 / 历史加载只在用户本来就在底部时才跟随,避免把上翻的用户拽回去。
    const userJustSent = grew && lastMsg?.role === 'user'
    if (userJustSent || isAtBottom) {
      // scrollToBottom() 只滚外层 messagesRegion;react-window 的 VariableSizeList
      // 自带内层滚动容器,新消息追加后内层 scrollTop 不会自动跟随,必须显式调
      // scrollToItem 把内层也滚到最后一条,否则新气泡落在内层可视区下方看不见。
      scrollToBottom()
      if (messages.length > 0) {
        listRef.current?.scrollToItem(messages.length - 1, 'end')
      }
    }
    lastCount.current = messages.length
  }, [messages.length, lastContent, lastMsg?.role, isAtBottom, scrollToBottom])

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
