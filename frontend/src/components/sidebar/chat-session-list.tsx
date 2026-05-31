import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useSnapshot } from 'valtio'
import {
  chatSessionsActions,
  chatSessionsState,
} from '@/store/chat-sessions'
import type { ChatSession } from '@/types/chat'
import { Skeleton } from '@/components/states/Skeleton'
import { EmptyState } from '@/components/states/EmptyState'
import { Icon } from '@/components/shared/Icon'
import styles from '@/styles/app-shell.module.scss'

export interface ChatSessionListProps {
  query?: string
}

type DateGroup = '今天' | '昨天' | '上周' | '更早'

function dateGroupOf(iso: string): DateGroup {
  const d = new Date(iso)
  const now = new Date()
  const day = 86400000
  const diff = now.getTime() - d.getTime()
  if (now.toDateString() === d.toDateString()) return '今天'
  const yesterday = new Date(now.getTime() - day)
  if (yesterday.toDateString() === d.toDateString()) return '昨天'
  if (diff < 7 * day) return '上周'
  return '更早'
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  if (now.toDateString() === d.toDateString()) {
    return d.toTimeString().slice(0, 5) // HH:mm
  }
  return d.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

interface RenameInputProps {
  initialValue: string
  onSubmit: (newValue: string) => void
  onCancel: () => void
}

function RenameInput({ initialValue, onSubmit, onCancel }: RenameInputProps) {
  const [v, setV] = useState(initialValue)
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => {
    ref.current?.focus()
    ref.current?.select()
  }, [])

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      onSubmit(v)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onCancel()
    }
  }

  return (
    <input
      ref={ref}
      data-testid="rename-input"
      className={styles.renameInput}
      value={v}
      onChange={(e) => setV(e.target.value)}
      onKeyDown={onKey}
      onBlur={onCancel}
      onClick={(e) => e.stopPropagation()}
    />
  )
}

export function ChatSessionList({ query = '' }: ChatSessionListProps) {
  const snap = useSnapshot(chatSessionsState)
  const navigate = useNavigate()
  const params = useParams<{ session_id?: string }>()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)

  useEffect(() => {
    if (snap.status === 'idle') {
      chatSessionsActions.loadSessions().catch(() => {})
    }
  }, [snap.status])

  useEffect(() => {
    function onDocClick() {
      setOpenMenuId(null)
    }
    if (openMenuId) document.addEventListener('click', onDocClick)
    return () => document.removeEventListener('click', onDocClick)
  }, [openMenuId])

  const groups = useMemo(() => {
    const filtered = query
      ? snap.sessions.filter(
          (s) =>
            s.title.toLowerCase().includes(query.toLowerCase()) ||
            (s.last_msg_preview ?? '').toLowerCase().includes(query.toLowerCase()),
        )
      : [...snap.sessions]
    const acc: Record<DateGroup, ChatSession[]> = {
      今天: [],
      昨天: [],
      上周: [],
      更早: [],
    }
    for (const s of filtered) acc[dateGroupOf(s.updated_at)].push(s)
    return acc
  }, [snap.sessions, query])

  function handleRenameSubmit(id: string, newTitle: string, originalTitle: string) {
    const trimmed = newTitle.trim()
    if (trimmed && trimmed !== originalTitle) {
      void chatSessionsActions.renameSession(id, trimmed)
    }
    setEditingId(null)
  }

  if (snap.status === 'loading') {
    return (
      <div data-testid="sidebar-chat-session-list">
        <Skeleton variant="list" count={5} />
      </div>
    )
  }

  const totalShown = Object.values(groups).reduce((n, list) => n + list.length, 0)
  if (totalShown === 0) {
    return (
      <div data-testid="sidebar-chat-session-list">
        <EmptyState
          variant="list-empty"
          title={query ? '无匹配会话' : '还没有对话'}
          description={query ? '换个关键词试试' : '点击「新对话」开始'}
        />
      </div>
    )
  }

  return (
    <div data-testid="sidebar-chat-session-list">
      {(['今天', '昨天', '上周', '更早'] as DateGroup[]).map((g) => {
        const list = groups[g]
        if (list.length === 0) return null
        return (
          <div key={g}>
            <div className={styles.groupHeader}>{g}</div>
            {list.map((s) => (
              <div
                key={s.id}
                className={`${styles.session} ${params.session_id === s.id ? styles.active : ''}`}
                onClick={() => {
                  if (editingId === s.id) return
                  navigate(`/chat/${s.id}`)
                }}
                data-testid={`session-item-${s.id}`}
              >
                <div className={styles.sessionRow}>
                  {editingId === s.id ? (
                    <RenameInput
                      initialValue={s.title}
                      onSubmit={(v) => handleRenameSubmit(s.id, v, s.title)}
                      onCancel={() => setEditingId(null)}
                    />
                  ) : (
                    <div className={styles.sessionTitle}>{s.title}</div>
                  )}
                  <button
                    type="button"
                    aria-label="more"
                    className={styles.sessionMoreBtn}
                    data-testid={`session-more-${s.id}`}
                    onClick={(e) => {
                      e.stopPropagation()
                      setOpenMenuId(openMenuId === s.id ? null : s.id)
                    }}
                  >
                    <Icon name="more-horizontal" size={14} />
                  </button>
                  {openMenuId === s.id ? (
                    <div
                      className={styles.sessionMenu}
                      onClick={(e) => e.stopPropagation()}
                      data-testid={`session-menu-${s.id}`}
                    >
                      <button
                        type="button"
                        className={styles.sessionMenuItem}
                        data-testid={`session-rename-${s.id}`}
                        onClick={() => {
                          setEditingId(s.id)
                          setOpenMenuId(null)
                        }}
                      >
                        重命名
                      </button>
                      <button
                        type="button"
                        className={styles.sessionMenuItem}
                        data-testid={`session-delete-${s.id}`}
                        style={{ color: 'var(--ios-destructive, #ff3b30)' }}
                        onClick={() => {
                          setOpenMenuId(null)
                          chatSessionsActions.deleteSession(s.id).then(() => {
                            if (params.session_id === s.id) navigate('/chat', { replace: true })
                          }).catch(() => {})
                        }}
                      >
                        删除
                      </button>
                    </div>
                  ) : null}
                </div>
                {s.last_msg_preview ? (
                  <div className={styles.sessionPreview}>{s.last_msg_preview}</div>
                ) : null}
                <div className={styles.sessionMeta}>
                  {formatTime(s.updated_at)} · {s.message_count} turns
                </div>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}
