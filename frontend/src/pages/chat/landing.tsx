import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChatPane } from '@/components/chat/ChatPane'
import { chatSessionsActions } from '@/store/chat-sessions'

export function ChatLandingPage() {
  const navigate = useNavigate()
  useEffect(() => {
    let cancelled = false
    chatSessionsActions
      .getOrCreateLanding()
      .then((s) => {
        if (!cancelled) navigate(`/chat/${s.id}`, { replace: true })
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [navigate])
  return <ChatPane />
}

export default ChatLandingPage
