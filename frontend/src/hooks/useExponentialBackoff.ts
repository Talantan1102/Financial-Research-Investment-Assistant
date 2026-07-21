/**
 * frontend/src/hooks/useExponentialBackoff.ts
 *
 * Pure helper: 1s / 2s / 4s / 8s / 16s / 30s cap.
 * Spec § 4.5 / Q7. Used by the Run event transport on disconnect.
 */

const BASE_MS = 1000
const CAP_MS = 30_000

export function computeBackoffMs(attempt: number): number {
  if (attempt <= 0) return BASE_MS
  const delay = BASE_MS * 2 ** attempt
  return Math.min(delay, CAP_MS)
}
