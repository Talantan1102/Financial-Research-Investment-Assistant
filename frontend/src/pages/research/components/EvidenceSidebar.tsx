/**
 * EvidenceSidebar.tsx
 * Right collapsible evidence list for D output report view.
 * Shows chunk_id references aggregated from all 6 sections.
 * Simplified: displays chunk_id as label + tooltip (no KB fetch, Task 7 可丰富).
 */

import { useState } from 'react'
import { Tag, Tooltip } from 'antd'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'
import type { InvestmentDueDiligenceReport } from '@/types/research'

// ── Design tokens ─────────────────────────────────────────────────────────────
const TOKEN = {
  cardBg: '#ffffff',
  borderColor: '#e8e4dc',
  textPrimary: '#1a1d21',
  textSecondary: '#5d6875',
  textTertiary: '#8a96a3',
  accentBlue: '#1d4ed8',
}

// ── Evidence entry ─────────────────────────────────────────────────────────────
interface EvidenceEntry {
  chunkId: string
  sections: string[]
}

// ── Collect all evidence references across sections ───────────────────────────
function collectEvidence(report: InvestmentDueDiligenceReport): EvidenceEntry[] {
  const map = new Map<string, Set<string>>()

  const addEvidence = (sectionLabel: string, ids: string[]) => {
    for (const id of ids) {
      if (!id) continue
      if (!map.has(id)) map.set(id, new Set())
      map.get(id)!.add(sectionLabel)
    }
  }

  // v0.9.x: backend 偶尔回传 partial report_json (缺 6 节字段) — 加 optional chain
  // guard,缺字段时跳过对应 section 而不是 crash 整个 React tree.
  addEvidence('公司概况', report.target_overview?.evidence ?? [])
  addEvidence('法律资质', report.legal_qualification?.evidence ?? [])
  addEvidence('财务分析', report.financial_analysis?.evidence ?? [])
  addEvidence('行业分析', report.industry_analysis?.evidence ?? [])
  addEvidence('风险评估', report.risk_assessment?.evidence ?? [])
  addEvidence('投资建议', report.investment_recommendation?.evidence ?? [])

  return Array.from(map.entries()).map(([chunkId, sectionsSet]) => ({
    chunkId,
    sections: Array.from(sectionsSet),
  }))
}

// ── Props ─────────────────────────────────────────────────────────────────────
interface EvidenceSidebarProps {
  report: InvestmentDueDiligenceReport
  collapsed: boolean
  onToggle: () => void
  style?: React.CSSProperties
  className?: string
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function EvidenceSidebar({
  report,
  collapsed,
  onToggle,
  style,
  className,
}: EvidenceSidebarProps) {
  const [highlightId, setHighlightId] = useState<string | null>(null)
  const entries = collectEvidence(report)

  return (
    <div
      className={className}
      style={{
        position: 'relative',
        ...style,
      }}
    >
      {/* Toggle button */}
      <button
        onClick={onToggle}
        style={{
          position: 'absolute',
          left: collapsed ? -12 : -16,
          top: 20,
          zIndex: 10,
          background: TOKEN.cardBg,
          border: `1px solid ${TOKEN.borderColor}`,
          borderRadius: '50%',
          width: 28,
          height: 28,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          boxShadow: '0 1px 4px rgba(0,0,0,0.10)',
          color: TOKEN.textSecondary,
          padding: 0,
          transition: 'box-shadow 0.15s',
        }}
        title={collapsed ? '展开证据列表' : '折叠证据列表'}
      >
        {collapsed ? <RightOutlined style={{ fontSize: 10 }} /> : <LeftOutlined style={{ fontSize: 10 }} />}
      </button>

      {!collapsed && (
        <div
          style={{
            backgroundColor: TOKEN.cardBg,
            border: `1px solid ${TOKEN.borderColor}`,
            borderRadius: 10,
            padding: '16px',
            position: 'sticky',
            top: 16,
            maxHeight: 'calc(100vh - 80px)',
            overflowY: 'auto',
          }}
        >
          <div
            style={{
              fontSize: 12,
              color: TOKEN.textTertiary,
              fontWeight: 600,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              marginBottom: 10,
            }}
          >
            引用依据 ({entries.length})
          </div>

          {entries.length === 0 ? (
            <div style={{ fontSize: 12, color: TOKEN.textTertiary }}>暂无引用</div>
          ) : (
            entries.map(({ chunkId, sections }) => (
              <Tooltip
                key={chunkId}
                title={`来源章节: ${sections.join(', ')}`}
                placement="left"
              >
                <div
                  onClick={() => setHighlightId(highlightId === chunkId ? null : chunkId)}
                  style={{
                    padding: '6px 8px',
                    marginBottom: 4,
                    borderRadius: 6,
                    cursor: 'pointer',
                    backgroundColor:
                      highlightId === chunkId ? 'rgba(29,78,216,0.06)' : 'transparent',
                    border: `1px solid ${highlightId === chunkId ? TOKEN.accentBlue : 'transparent'}`,
                    transition: 'background 0.15s, border-color 0.15s',
                  }}
                >
                  <div
                    style={{
                      fontFamily: '"SF Mono", "JetBrains Mono", Consolas, monospace',
                      fontSize: 11,
                      color: TOKEN.accentBlue,
                      wordBreak: 'break-all',
                      lineHeight: 1.4,
                    }}
                  >
                    {chunkId}
                  </div>
                  <div style={{ marginTop: 3, display: 'flex', flexWrap: 'wrap', gap: 2 }}>
                    {sections.map((s) => (
                      <Tag
                        key={s}
                        style={{
                          fontSize: 10,
                          padding: '0 4px',
                          lineHeight: '16px',
                          height: 16,
                          borderColor: TOKEN.borderColor,
                          color: TOKEN.textTertiary,
                          backgroundColor: '#f5f2ec',
                          margin: 0,
                        }}
                      >
                        {s}
                      </Tag>
                    ))}
                  </div>
                </div>
              </Tooltip>
            ))
          )}
        </div>
      )}
    </div>
  )
}
