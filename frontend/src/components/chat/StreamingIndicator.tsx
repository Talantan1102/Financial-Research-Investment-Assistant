import { useSnapshot } from 'valtio'
import { currentChatState } from '@/store/current-chat'

export function StreamingIndicator() {
  const snap = useSnapshot(currentChatState)
  if (snap.streamingStatus === 'idle') return null
  return (
    <div data-testid="streaming-indicator" style={{ padding: 8, color: '#888', fontStyle: 'italic' }}>
      {snap.streamingStatus === 'streaming' && '思考中…'}
      {snap.streamingStatus === 'reconnecting' && '重连中…'}
      {snap.streamingStatus === 'error' && (snap.errorMessage ?? '出错')}
    </div>
  )
}
