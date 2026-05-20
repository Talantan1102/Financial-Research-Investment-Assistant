import { useEffect, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useSnapshot } from 'valtio'
import {
  chatSessionsActions,
  chatSessionsState,
} from '@/store/chat-sessions'
import type { ChatSession } from '@/types/chat'
import { Skeleton } from '@/components/states/Skeleton'
import { EmptyState } from '@/components/states/EmptyState'
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

export function ChatSessionList({ query = '' }: ChatSessionListProps) {
  const snap = useSnapshot(chatSessionsState)
  const navigate = useNavigate()
  const params = useParams<{ session_id?: string }>()

  useEffect(() => {
    if (snap.status === 'idle') {
      chatSessionsActions.loadSessions().catch(() => {})
    }
  }, [snap.status])

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
    for (const s of filtered) acc[dateGroupOf(s.last_active_at)].push(s)
    return acc
  }, [snap.sessions, query])

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
                onClick={() => navigate(`/chat/${s.id}`)}
                data-testid={`session-item-${s.id}`}
              >
                <div className={styles.sessionTitle}>{s.title}</div>
                {s.last_msg_preview ? (
                  <div className={styles.sessionPreview}>{s.last_msg_preview}</div>
                ) : null}
                <div className={styles.sessionMeta}>
                  {formatTime(s.last_active_at)} · {s.message_count} turns
                </div>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}
