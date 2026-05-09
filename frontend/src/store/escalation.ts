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

export type EscalationPhase = 'idle' | 'draft' | 'confirmed' | 'researching' | 'done' | 'error'

export interface EscalationState {
  phase: EscalationPhase
  packet_draft: EscalationPacket | null
  user_edits: FieldEdit[]
  research_progress: ResearchProgress
  error: string | null
  dialog_open: boolean
  session_id: string | null
}

const INITIAL: EscalationState = {
  phase: 'idle',
  packet_draft: null,
  user_edits: [],
  research_progress: { stage: 'idle' },
  error: null,
  dialog_open: false,
  session_id: null,
}

export const escalationState = proxy<EscalationState>({ ...INITIAL })

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
  },
}
