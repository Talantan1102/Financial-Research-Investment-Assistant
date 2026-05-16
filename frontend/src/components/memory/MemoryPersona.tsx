import { Alert, Button, Spin } from 'antd'
import { useEffect, useState } from 'react'

import { fetchPersona, type PersonaItem, type PersonaListResponse } from '@/api/personaApi'

import * as S from './MemoryPersona.styles'

export interface MemoryPersonaProps {
  /** test 注入用；正式渲染时不传 */
  initialData?: PersonaListResponse
}

export default function MemoryPersona({ initialData }: MemoryPersonaProps = {}) {
  const [data, setData] = useState<PersonaListResponse | null>(initialData ?? null)
  const [loading, setLoading] = useState(!initialData)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (initialData) return
    let cancelled = false
    setLoading(true)
    fetchPersona()
      .then((resp) => {
        if (!cancelled) {
          setData(resp)
          setError(null)
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message || '加载失败')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [initialData])

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <Spin />
      </div>
    )
  }

  if (error) {
    return (
      <Alert
        type="error"
        message={`加载失败: ${error}`}
        action={
          <Button size="small" onClick={() => window.location.reload()}>
            重试
          </Button>
        }
      />
    )
  }

  if (!data) return null

  const totalCount = data.user_declared.length + data.agent_inferred.length

  if (totalCount === 0) {
    return (
      <div style={S.fullEmpty}>
        <p>还没有任何记忆 — 跟 agent 多聊几句它会自己开始记，或者点 + 自己加</p>
      </div>
    )
  }

  return (
    <div>
      <Section
        title="你声明的"
        icon="👤"
        items={data.user_declared}
        emptyPlaceholderText="（暂无）"
        canAdd
      />
      <Section
        title="agent 观察到的"
        icon="🤖"
        items={data.agent_inferred}
        emptyPlaceholderText="（暂无）"
      />
    </div>
  )
}

interface SectionProps {
  title: string
  icon: string
  items: PersonaItem[]
  emptyPlaceholderText: string
  canAdd?: boolean
}

function Section({ title, icon, items, emptyPlaceholderText }: SectionProps) {
  return (
    <div style={S.sectionWrapper}>
      <div style={S.sectionHeader}>
        <span>{icon}</span>
        <span>{title}</span>
      </div>
      {items.length === 0 ? (
        <div style={S.emptyPlaceholder}>{emptyPlaceholderText}</div>
      ) : (
        items.map((it) => (
          <div key={it.id} style={S.itemRow} data-testid={`persona-item-${it.id}`}>
            <div style={{ flex: 1, lineHeight: 1.5 }}>{it.text}</div>
          </div>
        ))
      )}
    </div>
  )
}
