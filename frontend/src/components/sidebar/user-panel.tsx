import { useSnapshot } from 'valtio'
import { authState } from '@/store/auth'

export function UserPanel() {
  const snap = useSnapshot(authState)
  const name = snap.isLoggedIn && snap.user ? snap.user.username : 'anonymous'
  return (
    <div
      data-testid="sidebar-user-panel"
      style={{
        padding: '8px 4px',
        borderTop: '1px solid #eee',
        fontSize: 13,
      }}
    >
      {name}
    </div>
  )
}
