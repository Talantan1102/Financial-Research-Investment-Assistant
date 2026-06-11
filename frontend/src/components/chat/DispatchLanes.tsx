/**
 * frontend/src/components/chat/DispatchLanes.tsx
 *
 * dispatch_subagents fan-out progress — renders one row per parallel child
 * subtask (lane). Driven by currentChatState.dispatchLanes, which the store
 * seeds on dispatch_start, increments on child tool_end{lane}, and finalizes
 * on dispatch_end. Renders nothing when no dispatch is in flight.
 */

import { useSnapshot } from 'valtio'
import { currentChatState } from '@/store/current-chat'

const STATUS_ICON: Record<string, string> = {
  running: '⏳',
  ok: '✓',
  partial: '◐',
  failed: '✗',
}

export function DispatchLanes() {
  const snap = useSnapshot(currentChatState)
  if (snap.dispatchLanes.length === 0) return null
  return (
    <div className="dispatch-lanes" data-testid="dispatch-lanes">
      <div className="dispatch-lanes__title">并行子助手 ({snap.dispatchLanes.length})</div>
      {snap.dispatchLanes.map((lane) => (
        <div key={lane.subtask_id} className="dispatch-lane" data-status={lane.status}>
          <span className="dispatch-lane__icon">{STATUS_ICON[lane.status] ?? '•'}</span>
          <span className="dispatch-lane__goal">{lane.goal}</span>
          <span className="dispatch-lane__count">{lane.toolCount} 次取数</span>
        </div>
      ))}
    </div>
  )
}
