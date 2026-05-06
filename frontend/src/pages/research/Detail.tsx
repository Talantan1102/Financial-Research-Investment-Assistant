/**
 * frontend/src/pages/research/Detail.tsx
 *
 * v0.9.x research detail page (/research/:id) — editorial × terminal redesign.
 *
 * Layout (3-zone):
 *   ┌── header ─────────────────────────────────────────────┐
 *   │ eyebrow / title (Fraunces) / status pill / metadata    │
 *   ├──────────────────────────────────┬────────────────────┤
 *   │ MAIN                             │ RAIL                │
 *   │ - streaming → ProgressTimeline   │ - AgentStatusSidebar│
 *   │   + live markdown / shimmer      │ - CostLatency/Critic│
 *   │ - completed → ReportCanvas       │ - EvidenceSidebar   │
 *   └──────────────────────────────────┴─────────────────────┘
 *
 * SSE event → legacy component adapter:
 *   - reportState.streaming.progress (ProgressEvent[]) → TimelineEntry[]
 *   - last completed event → AgentStateMap (5 agents pipeline status)
 *   - critic_score (aggregate) → CriticScores
 */

import { useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Empty } from 'antd'
import { useSnapshot } from 'valtio'
import { marked } from 'marked'
import dayjs from 'dayjs'
import { reportState, reportActions } from '@/store/report'
import type { ProgressEvent } from '@/store/report'
import type {
  InvestmentDueDiligenceReport,
  AgentName,
  AgentStateMap,
  AgentStatus,
  CriticScores,
} from '@/types/research'
import ReportCanvas from '@/components/report-canvas'
import ExportButton from '@/components/export-button'
import ProgressTimeline, {
  type TimelineEntry,
} from './components/ProgressTimeline'
import AgentStatusSidebar from './components/AgentStatusSidebar'
import CostLatencyMetrics from './components/CostLatencyMetrics'
import EvidenceSidebar from './components/EvidenceSidebar'
import styles from './Detail.module.scss'

// ── Status pill labels ──────────────────────────────────────────────────
const STATUS_LABEL: Record<string, string> = {
  completed: 'Completed',
  streaming: 'In Progress',
  failed: 'Failed',
}

// ── SSE → Timeline adapter ──────────────────────────────────────────────
function buildTimelineEntries(
  progress: readonly ProgressEvent[],
  startTs: number | null,
): TimelineEntry[] {
  if (progress.length === 0) return []
  const t0 = startTs ?? progress[0].timestamp
  const entries: TimelineEntry[] = []

  for (const evt of progress) {
    const elapsedSec = (evt.timestamp - t0) / 1000
    const raw = (evt.raw ?? {}) as Record<string, unknown>

    if (evt.type === 'plan') {
      const subtasks = Array.isArray(raw.subtasks)
        ? (raw.subtasks as string[])
        : []
      entries.push({
        elapsedSec,
        agentLabel: 'Planner',
        summary: evt.message,
        bullets: subtasks.slice(0, 6),
        done: true,
      })
    } else if (evt.type === 'data_progress') {
      const tools =
        Array.isArray(raw.tools) && raw.tools.length > 0
          ? (raw.tools as string[])
          : Array.isArray(raw.tool_names_raw)
            ? (raw.tool_names_raw as string[])
            : []
      entries.push({
        elapsedSec,
        agentLabel: 'DataCollector',
        summary: evt.message,
        bullets: tools.slice(0, 6),
        done: true,
      })
    } else if (evt.type === 'insight') {
      const findings = Array.isArray(raw.findings)
        ? (raw.findings as string[])
        : []
      entries.push({
        elapsedSec,
        agentLabel: 'Analyst',
        summary: evt.message,
        bullets: findings.slice(0, 5),
        done: true,
      })
    } else if (evt.type === 'report_chunk') {
      // Skip individual chunk-level entries; only summary
      entries.push({
        elapsedSec,
        agentLabel: 'Writer',
        summary: evt.message,
        done: true,
      })
    } else if (evt.type === 'critic_score') {
      // Two flavors: per-scorer (has scorer field) vs aggregate (has scores)
      const scorer = typeof raw.scorer === 'string' ? raw.scorer : null
      if (scorer === 'aggregate' || raw.scores) {
        // Show aggregate as final critic entry
        entries.push({
          elapsedSec,
          agentLabel: 'Critic',
          summary: evt.message,
          done: true,
        })
      }
      // Per-scorer events fold into Critic state but don't pollute timeline
    } else if (evt.type === 'error') {
      entries.push({
        elapsedSec,
        agentLabel: 'System',
        summary: `❌ ${evt.message}`,
        done: true,
      })
    }
  }

  return entries
}

// ── SSE → AgentStateMap adapter ─────────────────────────────────────────
const AGENT_PIPELINE: AgentName[] = [
  'Planner',
  'DataCollector',
  'Analyst',
  'Writer',
  'Critic',
]

function buildAgentStates(
  progress: readonly ProgressEvent[],
  reportStatus: 'streaming' | 'completed' | 'failed',
): AgentStateMap {
  const map: AgentStateMap = {}

  // Initialize all agents to pending
  for (const name of AGENT_PIPELINE) {
    map[name] = { name, status: 'pending' }
  }

  if (reportStatus === 'completed') {
    for (const name of AGENT_PIPELINE) {
      map[name] = { name, status: 'done' }
    }
    return map
  }

  if (reportStatus === 'failed') {
    return map
  }

  // streaming — derive from event flow
  let lastCompletedIdx = -1
  for (const evt of progress) {
    if (evt.type === 'plan') lastCompletedIdx = Math.max(lastCompletedIdx, 0)
    else if (evt.type === 'data_progress')
      lastCompletedIdx = Math.max(lastCompletedIdx, 1)
    else if (evt.type === 'insight')
      lastCompletedIdx = Math.max(lastCompletedIdx, 2)
    else if (evt.type === 'report_chunk')
      lastCompletedIdx = Math.max(lastCompletedIdx, 3)
    else if (evt.type === 'critic_score') {
      const raw = (evt.raw ?? {}) as Record<string, unknown>
      if (raw.scorer === 'aggregate' || raw.scores) {
        lastCompletedIdx = Math.max(lastCompletedIdx, 4)
      }
    }
  }

  for (let i = 0; i < AGENT_PIPELINE.length; i++) {
    const name = AGENT_PIPELINE[i]
    let status: AgentStatus
    if (i <= lastCompletedIdx) status = 'done'
    else if (i === lastCompletedIdx + 1) status = 'running'
    else status = 'pending'
    map[name] = { name, status }
  }

  return map
}

// ── SSE → Critic scores adapter ─────────────────────────────────────────
function extractCriticScores(
  progress: readonly ProgressEvent[],
): CriticScores | null {
  for (let i = progress.length - 1; i >= 0; i--) {
    const evt = progress[i]
    if (evt.type !== 'critic_score') continue
    const raw = (evt.raw ?? {}) as Record<string, unknown>
    if (raw.scores && typeof raw.scores === 'object') {
      const s = raw.scores as Record<string, number>
      const overall = typeof raw.overall === 'number' ? raw.overall : 0
      return {
        data_quality: Number(s.factuality ?? s.data_quality ?? 0),
        logical_coherence: Number(s.structure ?? s.logical_coherence ?? 0),
        client_fit: Number(s.input_context ?? s.client_fit ?? 0),
        risk_disclosure: Number(s.coverage ?? s.risk_disclosure ?? 0),
        regulatory_compliance: Number(
          s.factuality ?? s.regulatory_compliance ?? 0,
        ),
        actionability: Number(s.insight ?? s.actionability ?? 0),
        total: Number(overall),
      }
    }
  }
  return null
}

// ── Main page ───────────────────────────────────────────────────────────
export default function ResearchDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const snap = useSnapshot(reportState)
  const [evidenceCollapsed, setEvidenceCollapsed] = useState(false)

  useEffect(() => {
    if (id) void reportActions.fetchDetail(id)
    return () => {
      reportActions.clearCurrent()
    }
  }, [id])

  const status = snap.current?.status
  useEffect(() => {
    if (id && status === 'streaming') {
      reportActions.startStreaming(id)
    }
  }, [status, id])

  // Derive timeline + agent states + critic scores from SSE progress
  const timelineEntries = useMemo(
    () =>
      buildTimelineEntries(
        snap.streaming.progress as readonly ProgressEvent[],
        snap.streaming.progress[0]?.timestamp ?? null,
      ),
    [snap.streaming.progress],
  )
  const agentStates = useMemo(
    () =>
      buildAgentStates(
        snap.streaming.progress as readonly ProgressEvent[],
        (status as 'streaming' | 'completed' | 'failed') ?? 'streaming',
      ),
    [snap.streaming.progress, status],
  )
  const criticScores = useMemo(
    () => extractCriticScores(snap.streaming.progress as readonly ProgressEvent[]),
    [snap.streaming.progress],
  )

  // Loading
  if (snap.currentLoading && !snap.current) {
    return (
      <div className={styles.page}>
        <div className={styles.loadingFull}>
          <span className="as-eyebrow">Loading research</span>
          <div className="as-shimmer" style={{ width: 280, height: 14 }} />
        </div>
      </div>
    )
  }

  if (!snap.current) {
    return (
      <div className={styles.page}>
        <div className={styles.empty}>
          <div className={styles.empty__icon}>404</div>
          <div className={styles.empty__text}>未找到该研报</div>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={null} />
        </div>
      </div>
    )
  }

  const r = snap.current
  const statusKey = (r.status as 'streaming' | 'completed' | 'failed') ?? 'streaming'
  const liveMd =
    typeof snap.streaming.partialSections.report_markdown === 'string'
      ? (snap.streaming.partialSections.report_markdown as string)
      : ''

  return (
    <div className={styles.page}>
      <div className={styles.shell}>
        {/* ── Header ─────────────────────────────────────── */}
        <header className={styles.header}>
          <div className={styles.identity}>
            <div className={styles.eyebrow}>
              <span
                className={styles.crumb}
                style={{ cursor: 'pointer' }}
                onClick={() => navigate('/research')}
              >
                AlphaScout / Research
              </span>
              <span className={styles.arrow}>→</span>
              {r.target_ts_code && <span className={styles.ts}>{r.target_ts_code}</span>}
            </div>
            <h1 className={styles.title}>{r.target_name}</h1>
            <div className={styles.metaRow}>
              <span className={`${styles.statusPill} ${styles[statusKey]}`}>
                <span className={styles.statusDot} />
                {STATUS_LABEL[r.status] ?? r.status}
              </span>
              <span>
                <span className={styles.metaLabel}>Created</span>
                <span className={styles.metaValue}>
                  {dayjs(r.created_at).format('YYYY · MM · DD HH:mm')}
                </span>
              </span>
              <span>
                <span className={styles.metaLabel}>Cost</span>
                <span className={styles.metaValue}>
                  ¥ {r.cost.toFixed(2)}
                </span>
              </span>
            </div>
          </div>
          <div className={styles.actions}>
            {r.status === 'completed' && <ExportButton report={r} />}
          </div>
        </header>

        {/* ── Body grid ─────────────────────────────────── */}
        <div className={styles.body}>
          <div className={styles.main}>
            {/* Streaming OR completed canvas */}
            {r.status === 'streaming' && (
              <StreamingCanvas
                liveMd={liveMd}
                hasProgress={snap.streaming.progress.length > 0}
              />
            )}

            {r.status === 'streaming' && timelineEntries.length > 0 && (
              <section>
                <ProgressTimeline entries={timelineEntries} />
              </section>
            )}

            {r.status === 'completed' && (
              <ReportCanvas
                report={r.report_json as InvestmentDueDiligenceReport}
              />
            )}

            {r.status === 'failed' && (
              <div className={styles.canvas}>
                <div className={styles.canvasLabel}>Error</div>
                <div style={{ color: 'var(--as-danger)', fontSize: 14 }}>
                  研报生成失败 — 请重试或查看日志。
                </div>
              </div>
            )}
          </div>

          {/* ── Right rail ──────────────────────────────── */}
          <aside className={styles.rail}>
            <AgentStatusSidebar agentStates={agentStates} />
            <CostLatencyMetrics
              costCny={r.cost}
              latencyMs={
                r.status === 'completed'
                  ? Math.max(0, dayjs(r.updated_at ?? r.created_at).diff(r.created_at))
                  : snap.streaming.progress.length > 0
                    ? Date.now() - snap.streaming.progress[0].timestamp
                    : 0
              }
              criticScores={criticScores}
            />
            {r.status === 'completed' && r.report_json && (
              <EvidenceSidebar
                report={r.report_json as InvestmentDueDiligenceReport}
                collapsed={evidenceCollapsed}
                onToggle={() => setEvidenceCollapsed((v) => !v)}
              />
            )}
          </aside>
        </div>
      </div>
    </div>
  )
}

// ── Streaming canvas (live markdown OR shimmer) ─────────────────────────
function StreamingCanvas({
  liveMd,
  hasProgress,
}: {
  liveMd: string
  hasProgress: boolean
}) {
  return (
    <section className={styles.canvas}>
      <div className={styles.canvasLabel}>
        {liveMd ? 'Draft Report · live' : 'Research Stage'}
      </div>

      {liveMd ? (
        <div
          className={styles.streamingMarkdown}
          dangerouslySetInnerHTML={{ __html: marked.parse(liveMd) as string }}
        />
      ) : (
        <div className={styles.canvasEmpty}>
          <div className={`${styles.shimmerLine} ${styles.medium}`} />
          <div className={`${styles.shimmerLine}`} />
          <div className={`${styles.shimmerLine} ${styles.short}`} />
          <div className={`${styles.shimmerLine}`} />
          <div className={`${styles.shimmerLine} ${styles.tiny}`} />
          <div className={styles.streamingHint}>
            {hasProgress
              ? 'Five-agent research in flight — drafting once data + analysis arrive.'
              : 'Spinning up research graph — first event in ~10s.'}
          </div>
        </div>
      )}
    </section>
  )
}
