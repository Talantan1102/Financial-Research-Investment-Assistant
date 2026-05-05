/**
 * ProgressTimeline.tsx
 * Business-friendly "research log" — each SSE event produces one log entry.
 * Shows elapsed time + summary text (+ optional bullet sub-items).
 * Agent names are intentionally hidden from the main display; they live in
 * the collapsible "技术细节" panel in new.tsx.
 *
 * UX ref: Perplexity / OpenAI Deep Research / Kimi 探索版 — natural-language
 * research monologue, hiding internal pipeline details.
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
  /**
   * Agent label — retained for AgentStatusSidebar use in tech panel,
   * but NOT displayed in the main research log timeline.
   * @internal
   */
  agentLabel: string
  /** Business-friendly one-line summary (may include emoji prefix) */
  summary: string
  /** Optional bullet items (subtask descriptions / tool labels / findings) */
  bullets?: string[]
  /** Whether this is a completed entry */
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
          padding: '20px 24px',
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
            marginBottom: 4,
          }}
        >
          研究进展
        </div>
        <div style={{ fontSize: 13, color: TOKEN.textSecondary, lineHeight: 1.8 }}>
          <p style={{ margin: 0 }}>正在初始化研究路径，请稍候...</p>
          <p style={{ margin: '8px 0 0', color: TOKEN.textTertiary, fontSize: 12 }}>
            完整研报通常需要 2–5 分钟。生成完毕后将自动跳转到报告页面。
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
        padding: '20px 24px',
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
          marginBottom: 14,
        }}
      >
        研究进展
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {entries.map((entry, idx) => (
          <div key={idx} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
            {/* Timeline dot + vertical connector */}
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                flexShrink: 0,
                paddingTop: 3,
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
                    minHeight: 18,
                    backgroundColor: TOKEN.borderColor,
                    marginTop: 4,
                  }}
                />
              )}
            </div>

            {/* Entry content — no agentLabel display */}
            <div style={{ flex: 1, paddingBottom: idx < entries.length - 1 ? 4 : 0 }}>
              {/* Timestamp + summary on same line */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: 8,
                  flexWrap: 'wrap',
                  marginBottom: entry.bullets && entry.bullets.length > 0 ? 6 : 0,
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
                  {formatElapsed(entry.elapsedSec)}
                </span>
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 500,
                    color: entry.done ? TOKEN.textPrimary : TOKEN.accentBlue,
                    lineHeight: 1.5,
                    wordBreak: 'break-word',
                  }}
                >
                  {entry.summary}
                </span>
              </div>

              {/* Bullet items (subtask descriptions / tool labels / findings) */}
              {entry.bullets && entry.bullets.length > 0 && (
                <div
                  style={{
                    paddingLeft: 10,
                    borderLeft: `2px solid ${TOKEN.borderColor}`,
                    marginLeft: 2,
                    marginTop: 2,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 1,
                  }}
                >
                  {entry.bullets.map((b, bi) => (
                    <div
                      key={bi}
                      style={{
                        fontSize: 12,
                        color: TOKEN.textSecondary,
                        lineHeight: 1.7,
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
