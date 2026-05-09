import { Spin } from 'antd'
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { chatSessionsActions } from '@/store/chat-sessions'

export function ChatLandingPage() {
  const navigate = useNavigate()
  useEffect(() => {
    let cancelled = false
    chatSessionsActions
      .createAndAdd()
      .then((s) => {
        if (!cancelled) navigate(`/chat/${s.id}`, { replace: true })
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [navigate])
  return (
    <div style={{ padding: 24 }}>
      <Spin /> Creating new chat…
    </div>
  )
}

export default ChatLandingPage
