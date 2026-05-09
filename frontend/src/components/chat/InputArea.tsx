import { SendOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react'
import { useSnapshot } from 'valtio'
import { currentChatState } from '@/store/current-chat'
import styles from '@/styles/chat.module.scss'

export interface InputAreaProps {
  sessionId?: string
  onSend?: (text: string) => void
  onAbort?: () => void
  onEscalate?: () => void
}

const MIN_HEIGHT = 44
const MAX_HEIGHT = 240

export function InputArea(props: InputAreaProps) {
  const [value, setValue] = useState('')
  const taRef = useRef<HTMLTextAreaElement>(null)
  const snap = useSnapshot(currentChatState)
  const streaming = snap.streaming_phase !== 'idle'

  const autoResize = useCallback(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    const next = Math.min(Math.max(ta.scrollHeight, MIN_HEIGHT), MAX_HEIGHT)
    ta.style.height = `${next}px`
  }, [])

  useEffect(() => {
    autoResize()
  }, [value, autoResize])

  const send = useCallback(() => {
    const text = value.trim()
    if (!text) return
    props.onSend?.(text)
    setValue('')
  }, [value, props])

  const onKey = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
        e.preventDefault()
        send()
      }
    },
    [send],
  )

  return (
    <div className={styles.inputArea} data-session={props.sessionId ?? ''}>
      <textarea
        ref={taRef}
        data-testid="input-textarea"
        className={styles.inputTextarea}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKey}
        placeholder={
          streaming ? '正在生成中...' : '问点什么 (Enter 发送, Shift+Enter 换行)'
        }
        rows={1}
      />
      <div className={styles.inputActions}>
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={send}
          disabled={!value.trim() || streaming}
          aria-label="发送"
        >
          发送
        </Button>
      </div>
    </div>
  )
}
