import { useSnapshot } from 'valtio'
import { currentChatState } from '@/store/current-chat'

export function CostMeter() {
  const snap = useSnapshot(currentChatState)
  return (
    <div data-testid="cost-meter" style={{ padding: '4px 12px', fontSize: 12, color: '#666' }}>
      ¥ {snap.cost_so_far.toFixed(4)}
    </div>
  )
}
