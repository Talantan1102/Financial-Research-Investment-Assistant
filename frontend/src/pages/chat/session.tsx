import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ChatPane } from '@/components/chat/ChatPane'
import { getChat } from '@/api/chatApi'
import { currentChatActions } from '@/store/current-chat'

export function ChatSessionPage() {
  const { session_id } = useParams<{ session_id: string }>()
  // Plan 2 Scenario B: 后端 GET /chats/{sid} 返回 active_task_id;非空时把它
  // 传给 ChatPane,ChatPane 自动 subscribe in-flight stream 继续看流。
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    if (!session_id) return
    setActiveTaskId(null)  // clear stale value on session switch
    getChat(session_id)
      .then((d) => {
        if (cancelled) return
        currentChatActions.setSession(d.session.id, d.messages)
        setActiveTaskId(d.active_task_id ?? null)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [session_id])

  return <ChatPane sessionId={session_id} activeTaskId={activeTaskId} />
}

export default ChatSessionPage
