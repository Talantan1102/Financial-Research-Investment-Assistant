import { beforeEach, describe, expect, it } from 'vitest'
import { currentChatActions, currentChatState } from '../current-chat'
import type { ChartEvent } from '@/types/chat'

describe('current-chat chart event', () => {
  beforeEach(() => {
    currentChatActions.setSession('sess-1', [])
  })

  it('chart event pushes a chart message carrying the figure', () => {
    const ev: ChartEvent = {
      type: 'chart',
      seq: 1,
      chart_id: 'req-1-2-0-0',
      figure: { data: [{ type: 'scatter' }], layout: {} },
    }
    currentChatActions.dispatchEvent(ev)
    const chartMsgs = currentChatState.messages.filter((m) => m.message_type === 'chart')
    expect(chartMsgs).toHaveLength(1)
    expect(chartMsgs[0].chart_spec?.figure.data).toHaveLength(1)
  })
})
