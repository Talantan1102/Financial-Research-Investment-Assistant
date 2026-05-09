/**
 * frontend/src/store/escalation.ts
 *
 * Escalation packet draft + user edits + research progress.
 * Plan 4a: store only. Plan 4b mounts <EscalationConfirmDialog> against this.
 */

import { proxy } from 'valtio'
import type {
  EscalationPacket,
  FieldEdit,
  ResearchProgress,
} from '@/types/escalation'
import type { ConfirmEscalationArgs, ConfirmEscalationResult } from '@/api/chatApi'

export type EscalationPhase = 'idle' | 'draft' | 'confirmed' | 'researching' | 'done' | 'error'

export interface EscalationState {
  phase: EscalationPhase
  packet_draft: EscalationPacket | null
  user_edits: FieldEdit[]
  research_progress: ResearchProgress
  error: string | null
  dialog_open: boolean
  session_id: string | null
  submitting: boolean
}

const INITIAL: EscalationState = {
  phase: 'idle',
  packet_draft: null,
  user_edits: [],
  research_progress: { stage: 'idle' },
  error: null,
  dialog_open: false,
  session_id: null,
  submitting: false,
}

export const escalationState = proxy<EscalationState>({ ...INITIAL })

// Dependency injection slot — replaced in tests via setConfirmEscalationFn()
let _confirmEscalation: (
  args: ConfirmEscalationArgs,
) => Promise<ConfirmEscalationResult> = async (args) => {
  const { confirmEscalation } = await import('@/api/chatApi')
  return confirmEscalation(args)
}

export function setConfirmEscalationFn(
  fn: (args: ConfirmEscalationArgs) => Promise<ConfirmEscalationResult>,
): void {
  _confirmEscalation = fn
}

export function recordUserEdit(edit: FieldEdit): void {
  const i = escalationState.user_edits.findIndex((e) => e.field_path === edit.field_path)
  if (i >= 0) {
    escalationState.user_edits.splice(i, 1, edit)
  } else {
    escalationState.user_edits.push(edit)
  }
}

export const escalationActions = {
  setPacketDraft(packet: EscalationPacket) {
    escalationState.packet_draft = packet
    escalationState.phase = 'draft'
    escalationState.user_edits = []
    escalationState.error = null
  },
  recordEdit(edit: FieldEdit) {
    escalationState.user_edits.push(edit)
  },
  confirm() {
    escalationState.phase = 'confirmed'
  },
  setResearchProgress(p: ResearchProgress) {
    escalationState.research_progress = p
    if (p.stage === 'done') escalationState.phase = 'done'
    if (p.stage === 'error') {
      escalationState.phase = 'error'
      escalationState.error = p.message ?? 'research failed'
    }
    if (
      p.stage === 'planner_running' ||
      p.stage === 'tool_running' ||
      p.stage === 'analyst_running' ||
      p.stage === 'writer_running' ||
      p.stage === 'critic_running'
    ) {
      escalationState.phase = 'researching'
    }
  },
  openDialog(sessionId: string) {
    escalationState.dialog_open = true
    escalationState.session_id = sessionId
  },
  closeDialog() {
    escalationState.dialog_open = false
  },
  reset() {
    escalationState.phase = INITIAL.phase
    escalationState.packet_draft = null
    escalationState.user_edits = []
    escalationState.research_progress = { stage: 'idle' }
    escalationState.error = null
    escalationState.dialog_open = false
    escalationState.session_id = null
    escalationState.submitting = false
  },
}

function applyUserEdits(
  draft: EscalationPacket,
  edits: readonly FieldEdit[],
): EscalationPacket {
  // Use JSON round-trip to deep-clone: structuredClone cannot handle valtio proxies
  const merged = JSON.parse(JSON.stringify(draft)) as EscalationPacket
  merged.session_metadata = {
    ...merged.session_metadata,
    user_edits: [...edits],
    user_confirmed_at: new Date().toISOString(),
  }
  return merged
}

export async function submitEscalation(): Promise<void> {
  if (!escalationState.packet_draft || !escalationState.session_id) return
  escalationState.submitting = true
  escalationState.error = null
  try {
    const confirmed = applyUserEdits(
      escalationState.packet_draft as EscalationPacket,
      escalationState.user_edits,
    )
    await _confirmEscalation({
      session_id: escalationState.session_id,
      packet: confirmed,
    })
    escalationState.dialog_open = false
  } catch (e) {
    escalationState.error = e instanceof Error ? e.message : String(e)
  } finally {
    escalationState.submitting = false
  }
}
