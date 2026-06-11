import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DispatchLanes } from '@/components/chat/DispatchLanes'
import { currentChatActions } from '@/store/current-chat'

describe('DispatchLanes', () => {
  beforeEach(() => currentChatActions.reset())

  it('renders nothing when no lanes', () => {
    const { container } = render(<DispatchLanes />)
    expect(container.firstChild).toBeNull()
  })

  it('renders one row per lane with status', () => {
    currentChatActions.dispatchEvent({
      type: 'dispatch_start',
      seq: 1,
      n: 2,
      subtasks: [
        { subtask_id: 'sub-0', goal: '查茅台' },
        { subtask_id: 'sub-1', goal: '查五粮液' },
      ],
    } as never)
    render(<DispatchLanes />)
    expect(screen.getByTestId('dispatch-lanes')).toBeInTheDocument()
    expect(screen.getByText('查茅台')).toBeInTheDocument()
    expect(screen.getByText('查五粮液')).toBeInTheDocument()
  })
})
