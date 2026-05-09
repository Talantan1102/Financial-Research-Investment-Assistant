import { Input } from 'antd'
import { useState } from 'react'
import { escalationState } from '@/store/escalation'

export interface InlineEditFieldProps {
  fieldPath: string
  llmValue: unknown
  multiline?: boolean
}

export function InlineEditField({
  fieldPath,
  llmValue,
  multiline = false,
}: InlineEditFieldProps) {
  const [value, setValue] = useState(llmValue == null ? '' : String(llmValue))
  const InputComponent = multiline ? Input.TextArea : Input
  return (
    <InputComponent
      value={value}
      data-field-path={fieldPath}
      onChange={(e: { target: { value: string } }) => {
        const v = e.target.value
        setValue(v)
        const existingIdx = escalationState.user_edits.findIndex(
          (x) => x.field_path === fieldPath,
        )
        const edit = {
          field_path: fieldPath,
          llm_value: llmValue,
          user_value: v,
          edit_type: 'modify' as const,
        }
        if (existingIdx >= 0) {
          escalationState.user_edits[existingIdx] = edit
        } else {
          escalationState.user_edits.push(edit)
        }
      }}
    />
  )
}
