import { List } from 'antd'
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSnapshot } from 'valtio'
import {
  chatSessionsActions,
  chatSessionsState,
} from '@/store/chat-sessions'

export function ChatSessionList() {
  const snap = useSnapshot(chatSessionsState)
  const navigate = useNavigate()

  useEffect(() => {
    if (snap.status === 'idle') {
      chatSessionsActions.loadSessions().catch(() => {})
    }
  }, [snap.status])

  return (
    <div data-testid="sidebar-chat-session-list">
      <List
        size="small"
        loading={snap.status === 'loading'}
        dataSource={[...snap.sessions]}
        locale={{ emptyText: 'No chats yet' }}
        renderItem={(s) => (
          <List.Item
            key={s.id}
            style={{ cursor: 'pointer' }}
            onClick={() => navigate(`/chat/${s.id}`)}
          >
            {s.title}
          </List.Item>
        )}
      />
    </div>
  )
}
