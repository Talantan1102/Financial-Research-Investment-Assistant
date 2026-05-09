import { ChatSessionList } from '@/components/sidebar/chat-session-list'
import { NewChatButton } from '@/components/sidebar/new-chat-button'
import { PageNav } from '@/components/sidebar/page-nav'
import { UserPanel } from '@/components/sidebar/user-panel'

export function Sidebar() {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        padding: 12,
        gap: 12,
        borderRight: '1px solid #eee',
      }}
    >
      <NewChatButton />
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        <ChatSessionList />
      </div>
      <PageNav />
      <UserPanel />
    </div>
  )
}
