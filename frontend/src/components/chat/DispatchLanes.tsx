/**
 * frontend/src/components/chat/DispatchLanes.tsx
 *
 * dispatch_subagents fan-out progress — renders one row per parallel child
 * subtask (lane). Driven by currentChatState.dispatchLanes, which the store
 * seeds on dispatch_start, increments on child tool_end{lane}, and finalizes
 * on dispatch_end. Renders nothing when no dispatch is in flight.
 *
 * Self-contained inline styles (no CSS-module coupling) so the card is always
 * a distinct, visible block inside the scrollable message flow.
 */

import type { CSSProperties } from 'react'
import { useSnapshot } from 'valtio'
import { currentChatState } from '@/store/current-chat'

const STATUS_ICON: Record<string, string> = {
  running: '⏳',
  ok: '✓',
  partial: '◐',
  failed: '✗',
}

const STATUS_COLOR: Record<string, string> = {
  running: '#b45309', // amber-700
  ok: '#15803d', // green-700
  partial: '#b45309',
  failed: '#b91c1c', // red-700
}

const cardStyle: CSSProperties = {
  border: '1px solid var(--ios-separator, #e5e7eb)',
  borderRadius: 12,
  background: 'var(--ios-bg-elevated, #fbfbfd)',
  padding: '10px 14px',
  margin: '4px 0',
  fontSize: 13,
  boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
}

const titleStyle: CSSProperties = {
  fontWeight: 600,
  color: 'var(--ios-label-secondary, #6b7280)',
  marginBottom: 6,
}

const laneStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '3px 0',
  lineHeight: 1.35,
}

const goalStyle: CSSProperties = {
  flex: 1,
  minWidth: 0,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
  color: 'var(--ios-label, #111827)',
}

const countStyle: CSSProperties = {
  color: 'var(--ios-label-secondary, #9ca3af)',
  fontVariantNumeric: 'tabular-nums',
  flexShrink: 0,
}

export function DispatchLanes() {
  const snap = useSnapshot(currentChatState)
  if (snap.dispatchLanes.length === 0) return null
  return (
    <div className="dispatch-lanes" data-testid="dispatch-lanes" style={cardStyle}>
      <div className="dispatch-lanes__title" style={titleStyle}>
        并行子助手 ({snap.dispatchLanes.length})
      </div>
      {snap.dispatchLanes.map((lane) => (
        <div
          key={lane.subtask_id}
          className="dispatch-lane"
          data-status={lane.status}
          style={laneStyle}
        >
          <span
            className="dispatch-lane__icon"
            style={{ color: STATUS_COLOR[lane.status] ?? '#6b7280', flexShrink: 0 }}
          >
            {STATUS_ICON[lane.status] ?? '•'}
          </span>
          <span className="dispatch-lane__goal" style={goalStyle}>
            {lane.goal}
          </span>
          <span className="dispatch-lane__count" style={countStyle}>
            {lane.toolCount} 次取数
          </span>
        </div>
      ))}
    </div>
  )
}
