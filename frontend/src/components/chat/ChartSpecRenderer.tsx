import ReactECharts from 'echarts-for-react'
import type { ChartSpec } from '@/types/chat'

export interface ChartSpecRendererProps {
  spec: ChartSpec
}

export function ChartSpecRenderer({ spec }: ChartSpecRendererProps) {
  if (
    !spec ||
    spec.type !== 'echarts' ||
    !spec.option ||
    typeof spec.option !== 'object'
  ) {
    return (
      <div
        style={{
          padding: 12,
          border: '1px dashed #ff4d4f',
          color: '#ff4d4f',
        }}
      >
        chart_spec invalid
      </div>
    )
  }
  return <ReactECharts option={spec.option} style={{ height: 280, width: '100%' }} />
}
