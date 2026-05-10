import { CheckOutlined, CloseOutlined, EditOutlined } from '@ant-design/icons'
import { Button, Input, Space } from 'antd'
import { useState } from 'react'
import { useSnapshot } from 'valtio'
import { escalationState, recordUserEdit } from '@/store/escalation'

export interface InlineEditFieldProps {
  fieldPath: string
  llmValue: unknown
  multiline?: boolean
}

function asDisplay(v: unknown): string {
  return v == null ? '' : String(v)
}

export function InlineEditField({
  fieldPath,
  llmValue,
  multiline,
}: InlineEditFieldProps) {
  const initial = asDisplay(llmValue)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(initial)
  const snap = useSnapshot(escalationState)
  const persisted = snap.user_edits.find((e) => e.field_path === fieldPath)

  const displayValue = editing
    ? draft
    : persisted
      ? asDisplay(persisted.user_value)
      : initial

  const save = () => {
    const trimmed = draft.trim()
    const editType: 'modify' | 'delete' | 'add' =
      trimmed === '' && initial !== ''
        ? 'delete'
        : initial === '' && trimmed !== ''
          ? 'add'
          : 'modify'
    recordUserEdit({
      field_path: fieldPath,
      llm_value: llmValue,
      user_value: trimmed === '' ? null : trimmed,
      edit_type: editType,
    })
    setEditing(false)
  }

  const cancel = () => {
    setDraft(initial)
    setEditing(false)
  }

  const InputComp = multiline ? Input.TextArea : Input
  return (
    <Space.Compact style={{ width: '100%' }}>
      <InputComp
        value={displayValue}
        onChange={(e: { target: { value: string } }) => setDraft(e.target.value)}
        readOnly={!editing}
        autoSize={multiline ? { minRows: 2, maxRows: 6 } : undefined}
        data-field-path={fieldPath}
      />
      {editing ? (
        <>
          <Button
            icon={<CheckOutlined />}
            type="primary"
            onClick={save}
            aria-label="保存"
          />
          <Button
            icon={<CloseOutlined />}
            onClick={cancel}
            aria-label="取消"
          />
        </>
      ) : (
        <Button
          icon={<EditOutlined />}
          onClick={() => {
            setDraft(displayValue)
            setEditing(true)
          }}
          aria-label="编辑"
        />
      )}
    </Space.Compact>
  )
}
