import { Empty } from 'antd'
import { useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { getChat } from '@/api/chatApi'
import { useChatSSE } from '@/hooks/useChatSSE'
import { currentChatActions } from '@/store/current-chat'

export function ChatSessionPage() {
  const { session_id } = useParams<{ session_id: string }>()
  useChatSSE({ sessionId: session_id ?? null })

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

  return (
    <div
      data-testid="chat-pane-slot"
      style={{ padding: 24, height: '100%' }}
    >
      <Empty description="ChatPane (Plan 4b)" />
    </div>
  )
}

export default ChatSessionPage
