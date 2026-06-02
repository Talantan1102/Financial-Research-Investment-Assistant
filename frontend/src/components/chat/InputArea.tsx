import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react'
import { useSnapshot } from 'valtio'
import { currentChatState } from '@/store/current-chat'
import { Icon } from '@/components/shared/Icon'
import { SlashCommandMenu } from '@/components/chat/SlashCommandMenu'
import { SLASH_COMMANDS, parseSlashInput } from '@/components/chat/slashCommands'
import styles from '@/styles/chat.module.scss'

export interface InputAreaProps {
  sessionId?: string
  onSend?: (
    text: string,
    forced?: { forced_tool_name: string; forced_tool_args: Record<string, unknown> },
  ) => void
  onAbort?: () => void
  onEscalate?: () => void
  // Plan 3 Task 7: streaming 中按「停止生成」时,如果 store 有 active_task_id,
  // 调 onCancel(tid) → backend POST /chat/cancel/{tid}(worker partial commit);
  // 否则 fallback onAbort(纯前端 abort)。
  onCancel?: (taskId: string) => void
}

const MIN_HEIGHT = 24
const MAX_HEIGHT = 140
const MAX_CHARS = 4000

export function InputArea(props: InputAreaProps) {
  const [value, setValue] = useState('')
  const [pasteWarn, setPasteWarn] = useState<string | null>(null)
  const [menuActiveIdx, setMenuActiveIdx] = useState(0)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const snap = useSnapshot(currentChatState)
  // menu opens while the input is a bare "/word" (command being typed, no space yet)
  const menuOpen = /^\/\w*$/.test(value)
  const menuItems = SLASH_COMMANDS.filter((c) =>
    c.alias.slice(1).toLowerCase().startsWith(value.replace(/^\//, '').toLowerCase()),
  )
  const streaming =
    snap.streaming_phase !== 'idle' || snap.streamingStatus === 'streaming'
  const messages = snap.messages ?? []
  const hasContext = messages.length > 0

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

  const onPaste = useCallback((e: ClipboardEvent) => {
    const dt = e.clipboardData
    if (!dt) return
    const hasFile = Array.from(dt.items).some((it) => it.kind === 'file')
    if (hasFile) {
      setPasteWarn('暂不支持上传 (C.4 milestone)')
      e.preventDefault()
      setTimeout(() => setPasteWarn(null), 4000)
    }
  }, [])

  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.addEventListener('paste', onPaste)
    return () => ta.removeEventListener('paste', onPaste)
  }, [onPaste])

  useEffect(() => {
    function onKeyGlobal(e: globalThis.KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        if (streaming) props.onAbort?.()
      }
    }
    window.addEventListener('keydown', onKeyGlobal)
    return () => window.removeEventListener('keydown', onKeyGlobal)
  }, [streaming, props])

  const send = useCallback(() => {
    const text = value.trim()
    if (!text) return
    const parsed = parseSlashInput(text)
    if (parsed.kind === 'forced_tool') {
      props.onSend?.(parsed.displayMessage, {
        forced_tool_name: parsed.toolName,
        forced_tool_args: parsed.args,
      })
    } else {
      props.onSend?.(text)
    }
    setValue('')
  }, [value, props])

  const selectCommand = useCallback((alias: string) => {
    setValue(`${alias} `)
    setMenuActiveIdx(0)
    taRef.current?.focus()
  }, [])

  const onKey = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.nativeEvent.isComposing) return
      if (menuOpen && menuItems.length > 0) {
        if (e.key === 'ArrowDown') {
          e.preventDefault()
          setMenuActiveIdx((i) => (i + 1) % menuItems.length)
          return
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault()
          setMenuActiveIdx((i) => (i - 1 + menuItems.length) % menuItems.length)
          return
        }
        if (e.key === 'Enter' || e.key === 'Tab') {
          e.preventDefault()
          selectCommand(menuItems[menuActiveIdx].alias)
          return
        }
        if (e.key === 'Escape') {
          e.preventDefault()
          setValue('')
          return
        }
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        send()
      }
    },
    [menuOpen, menuItems, menuActiveIdx, selectCommand, send],
  )

  const onCancelClick = () => {
    if (snap.active_task_id && props.onCancel) {
      void props.onCancel(snap.active_task_id)
    } else {
      props.onAbort?.()
    }
  }

  return (
    <div data-session={props.sessionId ?? ''}>
      <div className={styles.composer}>
        <div className={styles.composerInput} style={{ position: 'relative' }}>
          <SlashCommandMenu
            open={menuOpen && menuItems.length > 0}
            query={value}
            onSelect={selectCommand}
          />
          {!streaming && hasContext ? (
            <button
              type="button"
              className={styles.escalateBtn}
              onClick={() => props.onEscalate?.()}
              aria-label="升级到深度研究"
              title="升级到深度研究"
            >
              <Icon name="plus-circle" size={18} />
            </button>
          ) : null}
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
        </div>
        {streaming ? (
          <button
            type="button"
            className={styles.cancelBtn}
            onClick={onCancelClick}
            aria-label="停止生成"
            title="停止生成"
          >
            <Icon name="stop" size={14} />
          </button>
        ) : (
          <button
            type="button"
            className={styles.sendBtn}
            onClick={send}
            disabled={!value.trim()}
            aria-label="发送"
            title="发送"
          >
            <Icon name="arrow-up" size={16} />
          </button>
        )}
      </div>
      <div className={styles.inputHint}>
        <kbd>Enter</kbd> 发送 · <kbd>⇧</kbd> + <kbd>Enter</kbd> 换行 · <kbd>⌘</kbd> + <kbd>K</kbd> 停止
      </div>
      {value.length > MAX_CHARS / 8 ? (
        <div
          className={styles.charCounter}
          data-warn={value.length > MAX_CHARS}
        >
          {value.length} / {MAX_CHARS}
        </div>
      ) : null}
      {pasteWarn ? <div className={styles.pasteWarn}>{pasteWarn}</div> : null}
    </div>
  )
}
