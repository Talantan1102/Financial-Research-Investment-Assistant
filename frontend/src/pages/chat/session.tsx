import { useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { ChatPane } from '@/components/chat/ChatPane'
import { getChat } from '@/api/chatApi'
import { currentChatActions } from '@/store/current-chat'

export function ChatSessionPage() {
  const { session_id } = useParams<{ session_id: string }>()

  useEffect(() => {
    let cancelled = false
    if (!session_id) return
    getChat(session_id)
      .then((d) => {
        if (cancelled) return
        currentChatActions.setSession(d.session.id, d.messages)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [session_id])

  return <ChatPane sessionId={session_id} />
}

export default ChatSessionPage
