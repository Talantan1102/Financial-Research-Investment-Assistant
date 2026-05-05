/**
 * frontend/src/api/research.ts
 * Typed fetch + SSE EventSource for the /api/v0.5/research/* endpoints.
 */

import type {
  InvestmentDueDiligenceReport,
  ResearchRequest,
  ResearchRunSummary,
  SSEResearchEvent,
  TsCodeSuggestion,
} from '@/types/research'

export type { ResearchRunSummary, TsCodeSuggestion }

// ── API base (resolves via Vite proxy VITE_API_BASE) ─────────────────────────

const API_BASE = import.meta.env.VITE_API_BASE as string

function apiUrl(path: string): string {
  // Remove trailing slash from base, ensure leading slash on path.
  const base = (API_BASE ?? '').replace(/\/$/, '')
  return `${base}${path}`
}

// ── REST helpers ──────────────────────────────────────────────────────────────

/**
 * GET /api/v0.5/research/runs — list recent research run summaries.
 */
export async function listResearchRuns(): Promise<ResearchRunSummary[]> {
  const res = await fetch(apiUrl('/api/v0.5/research/runs'))
  if (!res.ok) {
    throw new Error(`listResearchRuns failed: ${res.status}`)
  }
  return res.json() as Promise<ResearchRunSummary[]>
}

/**
 * GET /api/v0.5/research/:id — fetch a full InvestmentDueDiligenceReport.
 */
export async function getResearchReport(
  id: string,
): Promise<InvestmentDueDiligenceReport> {
  const res = await fetch(apiUrl(`/api/v0.5/research/${id}`))
  if (!res.ok) {
    throw new Error(`getResearchReport failed: ${res.status}`)
  }
  return res.json() as Promise<InvestmentDueDiligenceReport>
}

// ── SSE submit ────────────────────────────────────────────────────────────────

/**
 * POST /api/v0.5/research — submit a research request as SSE stream.
 *
 * Mirrors the `deepsearch` pattern in api/session.ts (fetch + ReadableStream),
 * but wraps it in a simpler callback interface since SSE is one-directional here.
 *
 * Returns { abort } so callers can cancel mid-stream.
 */
export function submitResearch(
  req: ResearchRequest,
  onEvent: (e: SSEResearchEvent) => void,
  onError: (err: Error) => void,
): { abort: () => void } {
  const controller = new AbortController()

  // Fire and forget; errors surface via onError callback.
  void (async () => {
    try {
      const res = await fetch(apiUrl('/api/v0.5/research'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
        },
        body: JSON.stringify(req),
        signal: controller.signal,
      })

      if (!res.ok) {
        throw new Error(`research stream returned ${res.status}`)
      }

      if (!res.body) {
        throw new Error('response body is null')
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // SSE lines are separated by '\n\n'; each line starts with 'data: '.
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''

        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith('data:')) continue
          const json = line.slice('data:'.length).trim()
          if (!json) continue
          try {
            const event = JSON.parse(json) as SSEResearchEvent
            onEvent(event)
          } catch {
            // Silently skip malformed JSON lines.
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        // User-initiated abort — not an error.
        return
      }
      onError(err instanceof Error ? err : new Error(String(err)))
    }
  })()

  return {
    abort: () => controller.abort(),
  }
}

// ── Autocomplete ──────────────────────────────────────────────────────────────

/**
 * GET /api/v0.5/tushare/stock_basic_search?prefix=... — ts_code autocomplete.
 */
export async function autocompleteTsCode(
  prefix: string,
): Promise<TsCodeSuggestion[]> {
  const res = await fetch(
    apiUrl(
      `/api/v0.5/tushare/stock_basic_search?prefix=${encodeURIComponent(prefix)}`,
    ),
  )
  if (!res.ok) {
    throw new Error(`autocompleteTsCode failed: ${res.status}`)
  }
  return res.json() as Promise<TsCodeSuggestion[]>
}
