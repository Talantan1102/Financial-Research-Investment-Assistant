/**
 * AgentStatusSidebar.tsx
 * Vertically stacked 5-agent status indicator for C2 progress UI.
 * Used inside new.tsx progress overlay during SSE streaming.
 */

import { LoadingOutlined } from '@ant-design/icons'
import { Spin } from 'antd'
import type { AgentName, AgentState, AgentStateMap, SubtaskState } from '@/types/research'

// ── Design tokens ─────────────────────────────────────────────────────────────
const TOKEN = {
  cardBg: '#ffffff',
  borderColor: '#e8e4dc',
  textPrimary: '#1a1d21',
  textSecondary: '#5d6875',
  textTertiary: '#8a96a3',
  accentBlue: '#1d4ed8',
  accentGreen: '#27875a',
  accentYellow: '#b8860b',
  accentRed: '#c0392b',
}

// ── Agent order ───────────────────────────────────────────────────────────────
const AGENT_ORDER: AgentName[] = [
  'Planner',
  'DataCollector',
  'Analyst',
  'Writer',
  'Critic',
]

const AGENT_LABEL: Record<AgentName, string> = {
  Planner: '规划师',
  DataCollector: '数据采集',
  Analyst: '分析师',
  Writer: '撰写师',
  Critic: '评审官',
}

// ── Status icon ───────────────────────────────────────────────────────────────
function StatusIcon({ status }: { status: AgentState['status'] }) {
  switch (status) {
    case 'pending':
      return <span style={{ fontSize: 14, color: TOKEN.textTertiary }}>⚪</span>
    case 'running':
      return (
        <Spin
          indicator={<LoadingOutlined style={{ fontSize: 14, color: TOKEN.accentBlue }} spin />}
        />
      )
    case 'done':
      return <span style={{ fontSize: 14 }}>✅</span>
    case 'degraded':
      return <span style={{ fontSize: 14 }}>⚠️</span>
    case 'failed':
      return <span style={{ fontSize: 14 }}>❌</span>
    default:
      return <span style={{ fontSize: 14, color: TOKEN.textTertiary }}>⚪</span>
  }
}

// ── Subtask row ───────────────────────────────────────────────────────────────
function SubtaskRow({ task }: { task: SubtaskState }) {
  const color =
    task.status === 'done'
      ? TOKEN.accentGreen
      : task.status === 'running'
        ? TOKEN.accentBlue
        : task.status === 'failed'
          ? TOKEN.accentRed
          : TOKEN.textTertiary

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '3px 0 3px 28px',
      }}
    >
      <StatusIcon status={task.status} />
      <span style={{ fontSize: 11, color, flex: 1 }}>{task.label}</span>
    </div>
  )
}

// ── Agent row ─────────────────────────────────────────────────────────────────
function AgentRow({ state }: { state: AgentState }) {
  const labelColor =
    state.status === 'running'
      ? TOKEN.accentBlue
      : state.status === 'done'
        ? TOKEN.accentGreen
        : state.status === 'degraded'
          ? TOKEN.accentYellow
          : state.status === 'failed'
            ? TOKEN.accentRed
            : TOKEN.textTertiary

  return (
    <div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 0',
          borderBottom: `1px solid ${TOKEN.borderColor}`,
        }}
      >
        <StatusIcon status={state.status} />
        <span
          style={{
            fontSize: 13,
            fontWeight: state.status === 'running' ? 600 : 400,
            color: labelColor,
            flex: 1,
          }}
        >
          {AGENT_LABEL[state.name]}
        </span>
      </div>
      {state.subtasks?.map((st, i) => (
        <SubtaskRow key={i} task={st} />
      ))}
    </div>
  )
}

// ── Props ─────────────────────────────────────────────────────────────────────
interface AgentStatusSidebarProps {
  agentStates: AgentStateMap
  style?: React.CSSProperties
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function AgentStatusSidebar({
  agentStates,
  style,
}: AgentStatusSidebarProps) {
  return (
    <div
      style={{
        backgroundColor: TOKEN.cardBg,
        border: `1px solid ${TOKEN.borderColor}`,
        borderRadius: 10,
        padding: '16px 20px',
        minWidth: 200,
        ...style,
      }}
    >
      <div
        style={{
          fontSize: 12,
          color: TOKEN.textTertiary,
          fontWeight: 600,
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          marginBottom: 8,
        }}
      >
        Agent 进度
      </div>
      {AGENT_ORDER.map((name) => {
        const state: AgentState = agentStates[name] ?? {
          name,
          status: 'pending',
        }
        return <AgentRow key={name} state={state} />
      })}
    </div>
  )
}
