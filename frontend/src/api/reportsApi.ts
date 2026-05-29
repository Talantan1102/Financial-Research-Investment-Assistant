/**
 * TOMBSTONE — this file is intentionally broken to prevent re-use.
 *
 * reportsApi.ts was a zombie client with three bugs:
 *   1. Wrong path: /api/v0/reports (backend prefix is /reports) → 404
 *   2. Raw fetch without Authorization header → 401
 *   3. Ghost schema fields (title, cost_usd, content_md) not in backend → TypeError
 *
 * Use @/api/reports instead (axios request client, correct schema, auto-auth).
 *
 * This file is kept as a tombstone so TypeScript will error loudly at any
 * remaining import site rather than silently re-introducing the bugs.
 */

// Deliberately export nothing useful. Any import of this file is a mistake.
export type ResearchReportSummary = never
export type ResearchReportDetail = never

export function listReports(): never {
  throw new Error(
    '[reportsApi] REMOVED: use listReports from @/api/reports instead. ' +
    'This file was a zombie client hitting /api/v0/reports without auth.',
  )
}

export function getReport(_id: string): never {
  throw new Error(
    '[reportsApi] REMOVED: use getReport from @/api/reports instead. ' +
    'This file was a zombie client hitting /api/v0/reports/{id} without auth.',
  )
}
