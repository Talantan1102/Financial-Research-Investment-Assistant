/**
 * CostLatencyMetrics.tsx
 * Displays live cost / latency during C2 progress and Critic scores after done.
 */

import type { CriticScores } from '@/types/research'

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

const DAILY_BUDGET_CNY = 20

const CRITIC_DIMENSION_LABELS: Record<keyof Omit<CriticScores, 'total'>, string> = {
  data_quality: '数据质量',
  logical_coherence: '逻辑连贯',
  client_fit: '客户匹配',
  risk_disclosure: '风险披露',
  regulatory_compliance: '合规性',
  actionability: '可操作性',
}

// ── Props ─────────────────────────────────────────────────────────────────────
interface CostLatencyMetricsProps {
  costCny: number
  latencyMs: number
  criticScores: CriticScores | null
  style?: React.CSSProperties
}

// ── Score bar ─────────────────────────────────────────────────────────────────
function ScoreBar({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, score * 10))
  const color =
    score >= 8 ? TOKEN.accentGreen : score >= 6 ? TOKEN.accentBlue : '#c0392b'
  return (
    <div
      style={{
        height: 4,
        backgroundColor: '#e8e4dc',
        borderRadius: 2,
        overflow: 'hidden',
        flex: 1,
        marginLeft: 6,
      }}
    >
      <div
        style={{
          width: `${pct}%`,
          height: '100%',
          backgroundColor: color,
          borderRadius: 2,
          transition: 'width 0.5s ease',
        }}
      />
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function CostLatencyMetrics({
  costCny,
  latencyMs,
  criticScores,
  style,
}: CostLatencyMetricsProps) {
  const latencySec = (latencyMs / 1000).toFixed(1)
  const costDisplay = costCny.toFixed(4)
  const budgetPct = Math.min(100, (costCny / DAILY_BUDGET_CNY) * 100)
  const budgetColor =
    budgetPct >= 90 ? '#c0392b' : budgetPct >= 70 ? TOKEN.textSecondary : TOKEN.accentGreen

  return (
    <div
      style={{
        backgroundColor: TOKEN.cardBg,
        border: `1px solid ${TOKEN.borderColor}`,
        borderRadius: 10,
        padding: '16px 20px',
        ...style,
      }}
    >
      {/* Cost row */}
      <div style={{ marginBottom: 12 }}>
        <div
          style={{
            fontSize: 12,
            color: TOKEN.textTertiary,
            fontWeight: 600,
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
            marginBottom: 6,
          }}
        >
          费用 / 预算
        </div>
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 4,
            fontFamily: TOKEN.monoFont,
          }}
        >
          <span style={{ fontSize: 18, fontWeight: 700, color: TOKEN.textPrimary }}>
            ¥{costDisplay}
          </span>
          <span style={{ fontSize: 12, color: TOKEN.textTertiary }}>
            / ¥{DAILY_BUDGET_CNY.toString()} 日限
          </span>
        </div>
        {/* Budget progress bar */}
        <div
          style={{
            height: 4,
            backgroundColor: '#e8e4dc',
            borderRadius: 2,
            overflow: 'hidden',
            marginTop: 4,
          }}
        >
          <div
            style={{
              width: `${budgetPct}%`,
              height: '100%',
              backgroundColor: budgetColor,
              borderRadius: 2,
              transition: 'width 0.5s ease',
            }}
          />
        </div>
      </div>

      {/* Latency row */}
      <div style={{ marginBottom: criticScores ? 16 : 0 }}>
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
          耗时
        </div>
        <span
          style={{
            fontFamily: TOKEN.monoFont,
            fontSize: 18,
            fontWeight: 700,
            color: TOKEN.textPrimary,
          }}
        >
          {latencySec}s
        </span>
      </div>

      {/* Critic scores — only shown after done */}
      {criticScores && (
        <div>
          <div
            style={{
              fontSize: 12,
              color: TOKEN.textTertiary,
              fontWeight: 600,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              marginBottom: 8,
              borderTop: `1px solid ${TOKEN.borderColor}`,
              paddingTop: 12,
            }}
          >
            Critic 评分
          </div>
          {(
            Object.entries(CRITIC_DIMENSION_LABELS) as [
              keyof typeof CRITIC_DIMENSION_LABELS,
              string,
            ][]
          ).map(([key, label]) => (
            <div
              key={key}
              style={{
                display: 'flex',
                alignItems: 'center',
                marginBottom: 6,
                gap: 4,
              }}
            >
              <span style={{ fontSize: 11, color: TOKEN.textSecondary, width: 60, flexShrink: 0 }}>
                {label}
              </span>
              <ScoreBar score={criticScores[key]} />
              <span
                style={{
                  fontFamily: TOKEN.monoFont,
                  fontSize: 11,
                  color: TOKEN.textSecondary,
                  width: 24,
                  textAlign: 'right',
                  flexShrink: 0,
                }}
              >
                {criticScores[key].toFixed(1)}
              </span>
            </div>
          ))}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              borderTop: `1px solid ${TOKEN.borderColor}`,
              paddingTop: 6,
              marginTop: 4,
            }}
          >
            <span style={{ fontSize: 12, fontWeight: 600, color: TOKEN.textSecondary }}>
              综合得分
            </span>
            <span
              style={{
                fontFamily: TOKEN.monoFont,
                fontSize: 14,
                fontWeight: 700,
                color:
                  criticScores.total >= 8
                    ? TOKEN.accentGreen
                    : criticScores.total >= 6
                      ? TOKEN.accentBlue
                      : '#c0392b',
              }}
            >
              {criticScores.total.toFixed(1)} / 10
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
