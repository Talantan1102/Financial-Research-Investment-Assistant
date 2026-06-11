import { describe, it, expect, beforeEach } from 'vitest'
import { currentChatState, currentChatActions } from '@/store/current-chat'

describe('dispatch lanes', () => {
  beforeEach(() => currentChatActions.reset())

  it('builds lanes from dispatch_start and updates on tool_end', () => {
    currentChatActions.beginStreaming()
    currentChatActions.dispatchEvent({
      type: 'dispatch_start',
      seq: 1,
      n: 2,
      subtasks: [
        { subtask_id: 'sub-0', goal: '查茅台' },
        { subtask_id: 'sub-1', goal: '查五粮液' },
      ],
    } as never)
    expect(currentChatState.dispatchLanes.length).toBe(2)
    currentChatActions.dispatchEvent({
      type: 'tool_end',
      seq: 2,
      lane: 'sub-0',
      tool: 'get_stock_quote',
    } as never)
    const lane0 = currentChatState.dispatchLanes.find((l) => l.subtask_id === 'sub-0')
    expect(lane0?.toolCount).toBeGreaterThan(0)
    currentChatActions.dispatchEvent({
      type: 'dispatch_end',
      seq: 3,
      n: 2,
      results: [
        { subtask_id: 'sub-0', status: 'ok' },
        { subtask_id: 'sub-1', status: 'partial' },
      ],
    } as never)
    expect(
      currentChatState.dispatchLanes.find((l) => l.subtask_id === 'sub-1')?.status,
    ).toBe('partial')
  })

  it('clears dispatchLanes on reset and beginStreaming', () => {
    currentChatActions.dispatchEvent({
      type: 'dispatch_start',
      seq: 1,
      n: 1,
      subtasks: [{ subtask_id: 'sub-0', goal: '查茅台' }],
    } as never)
    expect(currentChatState.dispatchLanes.length).toBe(1)
    currentChatActions.beginStreaming()
    expect(currentChatState.dispatchLanes.length).toBe(0)
    currentChatActions.dispatchEvent({
      type: 'dispatch_start',
      seq: 2,
      n: 1,
      subtasks: [{ subtask_id: 'sub-0', goal: '查茅台' }],
    } as never)
    currentChatActions.reset()
    expect(currentChatState.dispatchLanes.length).toBe(0)
  })
})
