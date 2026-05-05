/**
 * ProgressTimeline.tsx
 * Displays a chronological list of agent actions during SSE streaming.
 * Each entry shows elapsed time + agent name + summary text (+ optional subtask bullets).
 *
 * UX fix (dogfood): replaces empty "生成提示" placeholder in progress overlay main area
 * with a meaningful real-time log of agent activity, reducing user wait anxiety.
 */

import type { CSSProperties } from 'react'

// ── Design tokens ─────────────────────────────────────────────────────────────
const TOKEN = {
  cardBg: '#ffffff',
  borderColor: '#e8e4dc',
  textPrimary: '#1a1d21',
  textSecondary: '#5d6875',
  textTertiary: '#8a96a3',
  accentBlue: '#1d4ed8',
  accentGreen: '#27875a',
  monoFont: '"SF Mono", "JetBrains Mono", Consolas, monospace',
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface TimelineEntry {
  /** Elapsed seconds since streaming started (shown as [MM:SS]) */
  elapsedSec: number
  /** Human-readable agent label, e.g. "规划师" */
  agentLabel: string
  /** One-line summary text */
  summary: string
  /** Optional bullet items (subtasks / tool names / etc.) */
  bullets?: string[]
  /** Whether this is a terminal / completed entry */
  done: boolean
}

interface ProgressTimelineProps {
  entries: TimelineEntry[]
  style?: CSSProperties
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatElapsed(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function ProgressTimeline({ entries, style }: ProgressTimelineProps) {
  if (entries.length === 0) {
    return (
      <div
        style={{
          backgroundColor: TOKEN.cardBg,
          border: `1px solid ${TOKEN.borderColor}`,
          borderRadius: 10,
          padding: '16px 20px',
          minHeight: 120,
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
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
          }}
        >
          进度摘要
        </div>
        <div style={{ fontSize: 13, color: TOKEN.textSecondary, lineHeight: 1.7 }}>
          <p style={{ margin: 0 }}>AI 正在初始化，请稍候...</p>
          <p style={{ margin: '8px 0 0', color: TOKEN.textTertiary, fontSize: 12 }}>
            报告通常需要 2–5 分钟完成。生成完毕后将自动跳转到报告页面。
          </p>
        </div>
      </div>
    )
  }

  return (
    <div
      style={{
        backgroundColor: TOKEN.cardBg,
        border: `1px solid ${TOKEN.borderColor}`,
        borderRadius: 10,
        padding: '16px 20px',
        minHeight: 120,
        maxHeight: '55vh',
        overflowY: 'auto',
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
          marginBottom: 12,
        }}
      >
        进度摘要
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {entries.map((entry, idx) => (
          <div key={idx} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
            {/* Timeline dot + vertical line */}
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                flexShrink: 0,
                paddingTop: 2,
              }}
            >
              <div
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  backgroundColor: entry.done ? TOKEN.accentGreen : TOKEN.accentBlue,
                  flexShrink: 0,
                }}
              />
              {idx < entries.length - 1 && (
                <div
                  style={{
                    width: 1,
                    flex: 1,
                    minHeight: 16,
                    backgroundColor: TOKEN.borderColor,
                    marginTop: 4,
                  }}
                />
              )}
            </div>

            {/* Content */}
            <div style={{ flex: 1, paddingBottom: idx < entries.length - 1 ? 6 : 0 }}>
              {/* Time + agent label */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: 6,
                  marginBottom: entry.bullets && entry.bullets.length > 0 ? 4 : 0,
                }}
              >
                <span
                  style={{
                    fontFamily: TOKEN.monoFont,
                    fontSize: 11,
                    color: TOKEN.textTertiary,
                    flexShrink: 0,
                  }}
                >
                  [{formatElapsed(entry.elapsedSec)}]
                </span>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    color: entry.done ? TOKEN.accentGreen : TOKEN.textSecondary,
                    flexShrink: 0,
                  }}
                >
                  {entry.agentLabel}
                </span>
                <span
                  style={{
                    fontSize: 12,
                    color: TOKEN.textPrimary,
                    lineHeight: 1.5,
                    wordBreak: 'break-word',
                  }}
                >
                  {entry.summary}
                </span>
              </div>

              {/* Bullet items (subtasks / tools) */}
              {entry.bullets && entry.bullets.length > 0 && (
                <div
                  style={{
                    paddingLeft: 8,
                    borderLeft: `2px solid ${TOKEN.borderColor}`,
                    marginLeft: 4,
                    marginTop: 2,
                  }}
                >
                  {entry.bullets.map((b, bi) => (
                    <div
                      key={bi}
                      style={{
                        fontSize: 11,
                        color: TOKEN.textSecondary,
                        lineHeight: 1.6,
                        paddingLeft: 4,
                      }}
                    >
                      • {b}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
