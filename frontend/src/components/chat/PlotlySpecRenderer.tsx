import createPlotlyComponent from 'react-plotly.js/factory'
import Plotly from 'plotly.js-dist-min'
import type { PlotlySpec } from '@/types/chat'

// 用 factory + 预构建 dist-min(避开全量 plotly.js 的 mapbox-gl exotic subdep)。
const Plot = createPlotlyComponent(Plotly)

export interface PlotlySpecRendererProps {
  spec: PlotlySpec
}

export function PlotlySpecRenderer({ spec }: PlotlySpecRendererProps) {
  if (
    !spec ||
    spec.type !== 'plotly' ||
    !spec.figure ||
    !Array.isArray(spec.figure.data)
  ) {
    return (
      <div style={{ padding: 12, border: '1px dashed #ff4d4f', color: '#ff4d4f' }}>
        plotly spec invalid
      </div>
    )
  }
  // figure 来自 valtio store(reactive/只读)。plotly 绘制时会就地 mutate(归一化
  // trace/layout,如写 line.color),直接传只读对象会抛 "Cannot assign to read only
  // property" 并被 react-plotly 静默吞掉 → 空图。深拷成普通可变对象再交给 plotly;
  // structuredClone 拷不了 valtio proxy,用 JSON 往返(figure 本就 JSON 可序列化)。
  const figure = JSON.parse(JSON.stringify(spec.figure)) as typeof spec.figure
  return (
    <Plot
      data={figure.data}
      layout={{ autosize: true, ...(figure.layout ?? {}) }}
      config={{ displaylogo: false, responsive: true }}
      style={{ width: '100%', height: 320 }}
      useResizeHandler
    />
  )
}
