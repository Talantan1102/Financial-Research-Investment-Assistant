import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ChatPane } from '@/components/chat/ChatPane'
import { currentChatActions } from '@/store/current-chat'
import { chatSessionsActions } from '@/store/chat-sessions'
import type { RunStatus } from '@/api/runApi'
import type { RunPause } from '@/hooks/useRunSSE'

export function ChatSessionPage() {
  const { session_id } = useParams<{ session_id: string }>()
  const [activeRun, setActiveRun] = useState<{ id: string; status: RunStatus } | null>(null)
  const [detailLoaded, setDetailLoaded] = useState(false)
  const [detailError, setDetailError] = useState(false)
  const [detailAttempt, setDetailAttempt] = useState(0)
  const [activePause, setActivePause] = useState<RunPause | null>(null)

  useEffect(() => {
    let cancelled = false
    if (!session_id) return
    currentChatActions.reset()
    setActiveRun(null)
    setDetailLoaded(false)
    setDetailError(false)
    setActivePause(null)
    chatSessionsActions.loadSessionDetail(session_id)
      .then((detail) => {
        if (cancelled) return
        currentChatActions.replaceWithDurableMessages(detail.id, detail.messages)
        setActiveRun(detail.active_run_id && detail.active_run_status
          ? { id: detail.active_run_id, status: detail.active_run_status }
          : null)
        setActivePause(
          detail.active_pause_type && detail.active_pause_request
            ? {
                type: detail.active_pause_type === 'approval' ? 'approval_request' : 'input_request',
                request: detail.active_pause_request,
              }
            : null,
        )
        setDetailLoaded(true)
      })
      .catch(() => {
        if (!cancelled) setDetailError(true)
      })
    return () => { cancelled = true }
  }, [detailAttempt, session_id])

  return <>
    {detailError ? (
      <div role="alert">
        会话加载失败，请重试
        <button type="button" onClick={() => setDetailAttempt((value) => value + 1)}>重试</button>
      </div>
    ) : null}
    <ChatPane
      sessionId={session_id}
      initialRunId={activeRun?.id}
      initialRunStatus={activeRun?.status}
      initialPause={activePause}
      sessionLoading={!detailLoaded}
    />
  </>
}

export default ChatSessionPage
