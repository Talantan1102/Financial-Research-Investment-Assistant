import { useState } from 'react'
import { List } from 'antd'
import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSnapshot } from 'valtio'
import {
  chatSessionsActions,
  chatSessionsState,
} from '@/store/chat-sessions'

export function ChatSessionList() {
  const snap = useSnapshot(chatSessionsState)
  const navigate = useNavigate()
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)

  useEffect(() => {
    if (snap.status === 'idle') {
      chatSessionsActions.loadSessions().catch(() => {})
    }
  }, [snap.status])

  function handleRenameSubmit(id: string, newTitle: string, originalTitle: string) {
    const trimmed = newTitle.trim()
    if (trimmed && trimmed !== originalTitle) {
      void chatSessionsActions.renameSession(id, trimmed)
    }
    setEditingId(null)
  }

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
            data-session-row
            className="group"
            style={{ cursor: 'pointer', position: 'relative', paddingRight: 0 }}
            onClick={() => {
              if (editingId !== s.id) navigate(`/chat/${s.id}`)
            }}
          >
            {editingId === s.id ? (
              <RenameInput
                initialValue={s.title}
                onSubmit={(v) => handleRenameSubmit(s.id, v, s.title)}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <span
                style={{
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {s.title}
              </span>
            )}

            {/* More (...) button — visible on hover */}
            <button
              type="button"
              aria-label="more"
              className="opacity-0 group-hover:opacity-100"
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                padding: '0 6px',
                fontSize: 14,
                lineHeight: 1,
                flexShrink: 0,
              }}
              onClick={(e) => {
                e.stopPropagation()
                setOpenMenuId(openMenuId === s.id ? null : s.id)
              }}
            >
              ...
            </button>

            {/* Dropdown menu */}
            {openMenuId === s.id && (
              <div
                style={{
                  position: 'absolute',
                  right: 0,
                  top: '100%',
                  marginTop: 2,
                  background: '#fff',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
                  borderRadius: 4,
                  border: '1px solid #f0f0f0',
                  zIndex: 10,
                  minWidth: 100,
                }}
                onMouseLeave={() => setOpenMenuId(null)}
              >
                <button
                  type="button"
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'left',
                    padding: '6px 12px',
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    fontSize: 13,
                  }}
                  onClick={(e) => {
                    e.stopPropagation()
                    setEditingId(s.id)
                    setOpenMenuId(null)
                  }}
                >
                  重命名
                </button>
                {/* TODO(v1.x): Delete session — 待 brainstorm 软删/硬删策略 */}
              </div>
            )}
          </List.Item>
        )}
      />
    </div>
  )
}

interface RenameInputProps {
  initialValue: string
  onSubmit: (value: string) => void
  onCancel: () => void
}

function RenameInput({ initialValue, onSubmit, onCancel }: RenameInputProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <input
      ref={inputRef}
      autoFocus
      defaultValue={initialValue}
      style={{
        flex: 1,
        background: 'transparent',
        outline: 'none',
        border: '1px solid #d9d9d9',
        borderRadius: 2,
        padding: '0 4px',
        fontSize: 13,
      }}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          onSubmit((e.currentTarget as HTMLInputElement).value)
        } else if (e.key === 'Escape') {
          onCancel()
        }
      }}
      onBlur={(e) => {
        onSubmit(e.currentTarget.value)
      }}
    />
  )
}
