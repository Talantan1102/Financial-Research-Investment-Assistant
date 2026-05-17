import { Alert, Button, Input, message, Modal, Popconfirm, Spin } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'

import {
  addPersonaItem,
  deletePersonaItem,
  fetchPersona,
  updatePersonaItem,
  type PersonaItem,
  type PersonaListResponse,
} from '@/api/personaApi'

import * as S from './MemoryPersona.styles'

export interface MemoryPersonaProps {
  initialData?: PersonaListResponse
}

export default function MemoryPersona({ initialData }: MemoryPersonaProps = {}) {
  const [data, setData] = useState<PersonaListResponse | null>(initialData ?? null)
  const [loading, setLoading] = useState(!initialData)
  const [error, setError] = useState<string | null>(null)
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [addText, setAddText] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editText, setEditText] = useState('')
  const [recentlyUpgradedId, setRecentlyUpgradedId] = useState<string | null>(null)
  const upgradeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(
    () => () => {
      if (upgradeTimerRef.current !== null) clearTimeout(upgradeTimerRef.current)
    },
    [],
  )

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await fetchPersona()
      setData(resp)
      setError(null)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!initialData) {
      void refresh()
    }
  }, [initialData, refresh])

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
          <Button size="small" onClick={() => void refresh()}>
            重试
          </Button>
        }
      />
    )
  }

  if (!data) return null

  const total = data.user_declared.length + data.agent_inferred.length

  const handleAdd = async () => {
    const text = addText.trim()
    if (!text) return
    setAdding(true)
    try {
      await addPersonaItem({ text, target_section: 'user' })
      setAddText('')
      setAddModalOpen(false)
      await refresh()
      void message.success('已添加')
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误'
      void message.error(`添加失败: ${msg}`)
    } finally {
      setAdding(false)
    }
  }

  const handleSaveEdit = async (item: PersonaItem) => {
    const text = editText.trim()
    if (!text) return
    try {
      const updated = await updatePersonaItem(item.id, text)
      setEditingId(null)
      if (item.source === 'agent' && updated.source === 'user') {
        setRecentlyUpgradedId(updated.id)
        void message.success('已迁到你的声明区')
        if (upgradeTimerRef.current !== null) clearTimeout(upgradeTimerRef.current)
        upgradeTimerRef.current = setTimeout(() => setRecentlyUpgradedId(null), 1500)
      }
      await refresh()
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误'
      void message.error(`保存失败: ${msg}`)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deletePersonaItem(id)
      await refresh()
      void message.success('已删除')
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误'
      void message.error(`删除失败: ${msg}`)
    }
  }

  if (total === 0) {
    return (
      <>
        <div style={S.fullEmpty}>
          <p>还没有任何记忆 — 跟 agent 多聊几句它会自己开始记，或者点 + 自己加</p>
          <Button type="primary" onClick={() => setAddModalOpen(true)}>
            添加我的第一条
          </Button>
        </div>
        <AddModal
          open={addModalOpen}
          text={addText}
          adding={adding}
          onChange={setAddText}
          onCancel={() => {
            setAddModalOpen(false)
            setAddText('')
          }}
          onOk={handleAdd}
        />
      </>
    )
  }

  return (
    <div>
      <Section
        title="你声明的"
        icon="👤"
        items={data.user_declared}
        canAdd
        onAdd={() => setAddModalOpen(true)}
        editingId={editingId}
        editText={editText}
        setEditingId={setEditingId}
        setEditText={setEditText}
        onSaveEdit={handleSaveEdit}
        onDelete={handleDelete}
        recentlyUpgradedId={recentlyUpgradedId}
      />
      <Section
        title="agent 观察到的"
        icon="🤖"
        items={data.agent_inferred}
        editingId={editingId}
        editText={editText}
        setEditingId={setEditingId}
        setEditText={setEditText}
        onSaveEdit={handleSaveEdit}
        onDelete={handleDelete}
        recentlyUpgradedId={recentlyUpgradedId}
      />
      <AddModal
        open={addModalOpen}
        text={addText}
        adding={adding}
        onChange={setAddText}
        onCancel={() => {
          setAddModalOpen(false)
          setAddText('')
        }}
        onOk={handleAdd}
      />
    </div>
  )
}

interface SectionProps {
  title: string
  icon: string
  items: PersonaItem[]
  canAdd?: boolean
  onAdd?: () => void
  editingId: string | null
  editText: string
  setEditingId: (id: string | null) => void
  setEditText: (s: string) => void
  onSaveEdit: (item: PersonaItem) => Promise<void>
  onDelete: (id: string) => Promise<void>
  recentlyUpgradedId: string | null
}

function Section({
  title,
  icon,
  items,
  canAdd,
  onAdd,
  editingId,
  editText,
  setEditingId,
  setEditText,
  onSaveEdit,
  onDelete,
  recentlyUpgradedId,
}: SectionProps) {
  return (
    <div style={S.sectionWrapper}>
      <div style={S.sectionHeader}>
        <span>{icon}</span>
        <span>{title}</span>
      </div>
      {items.length === 0 ? (
        <div style={S.emptyPlaceholder}>（暂无）</div>
      ) : (
        items.map((it) => {
          const rowStyle = recentlyUpgradedId === it.id ? S.itemRowHighlighted : S.itemRow
          if (editingId === it.id) {
            return (
              <div key={it.id} style={rowStyle}>
                <Input.TextArea
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  autoSize={{ minRows: 1, maxRows: 4 }}
                  style={{ flex: 1 }}
                />
                <div style={S.actions}>
                  <Button
                    size="small"
                    type="primary"
                    data-testid={`persona-save-${it.id}`}
                    onClick={() => void onSaveEdit(it)}
                  >
                    ✓
                  </Button>
                  <Button size="small" onClick={() => setEditingId(null)}>
                    ✗
                  </Button>
                </div>
              </div>
            )
          }
          return (
            <div key={it.id} style={rowStyle} data-testid={`persona-item-${it.id}`}>
              <div style={{ flex: 1, lineHeight: 1.5 }}>{it.text}</div>
              <div style={S.actions}>
                <Button
                  size="small"
                  type="text"
                  data-testid={`persona-edit-${it.id}`}
                  onClick={() => {
                    setEditingId(it.id)
                    setEditText(it.text)
                  }}
                >
                  ✏️
                </Button>
                <Popconfirm
                  title="确认删除？"
                  okText="确认"
                  cancelText="取消"
                  onConfirm={() => void onDelete(it.id)}
                >
                  <Button
                    size="small"
                    type="text"
                    danger
                    data-testid={`persona-delete-${it.id}`}
                  >
                    🗑️
                  </Button>
                </Popconfirm>
              </div>
            </div>
          )
        })
      )}
      {canAdd && (
        <Button block type="dashed" onClick={onAdd}>
          + 手动添加一条
        </Button>
      )}
    </div>
  )
}

interface AddModalProps {
  open: boolean
  text: string
  adding: boolean
  onChange: (s: string) => void
  onCancel: () => void
  onOk: () => void
}

function AddModal({ open, text, adding, onChange, onCancel, onOk }: AddModalProps) {
  return (
    <Modal
      open={open}
      title="添加一条画像"
      onCancel={onCancel}
      onOk={onOk}
      confirmLoading={adding}
      okText="保存"
      cancelText="取消"
    >
      <Input.TextArea
        value={text}
        onChange={(e) => onChange(e.target.value)}
        placeholder="输入一条画像，例如：风险偏好稳健"
        autoSize={{ minRows: 2, maxRows: 6 }}
        maxLength={500}
      />
    </Modal>
  )
}
