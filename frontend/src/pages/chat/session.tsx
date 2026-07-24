import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ChatPane } from '@/components/chat/ChatPane'
import { currentChatActions } from '@/store/current-chat'
import { chatSessionsActions } from '@/store/chat-sessions'
import type { RunStatus } from '@/api/runApi'
import type { RunRevision } from '@/api/runApi'
import type { RunPause } from '@/hooks/useRunSSE'

interface SessionDetailState {
  identity: string | null
  activeRun: { id: string; status: RunStatus } | null
  activePause: RunPause | null
  loaded: boolean
  error: boolean
  revisions: RunRevision[]
  latestRunId: string | null
  revisionCursor: string | null
  revisionsHasMore: boolean
}

const EMPTY_DETAIL: SessionDetailState = {
  identity: null,
  activeRun: null,
  activePause: null,
  loaded: false,
  error: false,
  revisions: [],
  latestRunId: null,
  revisionCursor: null,
  revisionsHasMore: false,
}

function SessionLoadingPane() {
  return (
    <div role="status" aria-label="Loading session">
      <textarea
        aria-label="Session loading"
        data-testid="input-textarea"
        disabled
      />
    </div>
  )
}

export function ChatSessionPage() {
  const { session_id } = useParams<{ session_id: string }>()
  const currentIdentityRef = useRef(session_id)
  currentIdentityRef.current = session_id
  const [detailState, setDetailState] = useState<SessionDetailState>(EMPTY_DETAIL)
  const [detailAttempt, setDetailAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    if (!session_id) return
    const identity = session_id
    currentChatActions.reset()
    setDetailState({ ...EMPTY_DETAIL, identity })
    chatSessionsActions.loadSessionDetail(identity)
      .then((detail) => {
        if (cancelled || currentIdentityRef.current !== identity) return
        currentChatActions.replaceWithDurableMessages(detail.id, detail.messages)
        setDetailState({
          identity,
          activeRun: detail.active_run_id && detail.active_run_status
            ? { id: detail.active_run_id, status: detail.active_run_status }
            : null,
          activePause: detail.active_pause_id && detail.active_pause_type && detail.active_pause_request
            ? {
                id: detail.active_pause_id,
                type: detail.active_pause_type === 'approval' ? 'approval_request' : 'input_request',
                request: detail.active_pause_request,
              }
            : null,
          loaded: true,
          error: false,
          revisions: detail.revisions,
          latestRunId: detail.latest_run_id,
          revisionCursor: detail.revisions_next_cursor ?? null,
          revisionsHasMore: detail.revisions_has_more ?? false,
        })
      })
      .catch(() => {
        if (!cancelled && currentIdentityRef.current === identity) {
          setDetailState({ ...EMPTY_DETAIL, identity, error: true })
        }
      })
    return () => { cancelled = true }
  }, [detailAttempt, session_id])

  const currentDetail = detailState.identity === session_id ? detailState : null

  return <>
    {currentDetail?.error ? (
      <div role="alert">
        会话加载失败，请重试
        <button type="button" onClick={() => setDetailAttempt((value) => value + 1)}>重试</button>
      </div>
    ) : null}
    {currentDetail?.loaded ? (
      <ChatPane
        key={session_id}
        sessionId={session_id}
        initialRunId={currentDetail.activeRun?.id}
        initialRunStatus={currentDetail.activeRun?.status}
        initialPause={currentDetail.activePause}
        initialRevisions={currentDetail.revisions}
        initialLatestRunId={currentDetail.latestRunId}
        initialRevisionCursor={currentDetail.revisionCursor}
        initialRevisionsHasMore={currentDetail.revisionsHasMore}
      />
    ) : currentDetail?.error ? null : <SessionLoadingPane />}
  </>
}

export default ChatSessionPage
