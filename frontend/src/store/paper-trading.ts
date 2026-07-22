import { proxy } from 'valtio'
import type {
  ApprovalCardPhase,
  ApprovalCardState,
  ApprovalPayload,
  ApprovalRequestEvent,
} from '@/types/paper-trading'

export interface PaperTradingState {
  approvals: Record<string, ApprovalCardState>
}

export const paperTradingState = proxy<PaperTradingState>({ approvals: {} })

function phaseFor(payload: ApprovalPayload): ApprovalCardPhase {
  return payload.preview ? 'preview' : 'draft'
}

export const paperTradingActions = {
  upsert(payload: ApprovalPayload | ApprovalRequestEvent): ApprovalCardState {
    const existing = paperTradingState.approvals[payload.approval_id]
    const next: ApprovalCardState = {
      ...(existing ?? {}),
      ...payload,
      phase: existing?.phase === 'submitting' ? existing.phase : phaseFor(payload),
      error: existing?.error ?? null,
    }
    paperTradingState.approvals[payload.approval_id] = next
    return next
  },
  setPreview(approvalId: string, preview: ApprovalCardState['preview']) {
    const card = paperTradingState.approvals[approvalId]
    if (!card) return
    card.preview = preview
    card.phase = 'preview'
    card.error = null
  },
  setSubmitting(approvalId: string) {
    const card = paperTradingState.approvals[approvalId]
    if (card) {
      card.phase = 'submitting'
      card.error = null
    }
  },
  setError(approvalId: string, error: string) {
    const card = paperTradingState.approvals[approvalId]
    if (card) {
      card.phase = 'error'
      card.error = error
    }
  },
  reset() {
    paperTradingState.approvals = {}
  },
}
