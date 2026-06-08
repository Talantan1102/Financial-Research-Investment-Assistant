import { useSnapshot } from 'valtio'
import { currentChatState } from '@/store/current-chat'
import { LoadingDots } from '@/components/states/LoadingDots'
import styles from '@/styles/chat.module.scss'

const PHASE_LABEL: Record<string, string> = {
  thinking: 'AI 在思考...',
  tool: '调用工具中...',
  writing: '写回答中...',
  research_planning: '研究规划中...',
  research_running: '研究执行中...',
  research_writing: '撰写研报中...',
  error: '发生错误',
}

export function StreamingIndicator() {
  const snap = useSnapshot(currentChatState)
  if (snap.streaming_phase === 'idle') return null
  const label = snap.streaming_phase_label ?? PHASE_LABEL[snap.streaming_phase] ?? ''
  // chatloop step_start{step,max_steps} → "第 N/M 步" progress hint.
  const progress = snap.loop_progress
  return (
    <div
      className={styles.streamingIndicator}
      data-testid="streaming-indicator-bar"
      data-phase={snap.streaming_phase}
    >
      <LoadingDots ariaLabel="streaming" />
      <span>{label}</span>
      {progress ? (
        <span className={styles.loopProgress} data-testid="loop-progress">
          第 {progress.step}/{progress.max_steps} 步
        </span>
      ) : null}
    </div>
  )
}
