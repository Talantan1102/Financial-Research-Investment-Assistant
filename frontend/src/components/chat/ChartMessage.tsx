import type { ChatMessage } from '@/types/chat'
import { PlotlySpecRenderer } from './PlotlySpecRenderer'

export interface ChartMessageProps {
  message: ChatMessage
}

export function ChartMessage({ message }: ChartMessageProps) {
  if (!message.chart_spec) return null
  return (
    <div data-testid="chart-message" style={{ width: '100%' }}>
      <PlotlySpecRenderer spec={message.chart_spec} />
    </div>
  )
}
