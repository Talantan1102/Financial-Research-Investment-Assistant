import createPlotlyComponent from 'react-plotly.js/factory'
import Plotly from 'plotly.js-dist-min'

// 用 factory + 预构建 dist-min(避开全量 plotly.js 的 mapbox-gl exotic subdep)。
const Plot = createPlotlyComponent(Plotly)

export interface PlotlyFigure {
  data: Record<string, unknown>[]
  layout?: Record<string, unknown>
}

export interface PlotlySpec {
  type: 'plotly'
  figure: PlotlyFigure
}

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
  return (
    <Plot
      data={spec.figure.data}
      layout={{ autosize: true, ...(spec.figure.layout ?? {}) }}
      config={{ displaylogo: false, responsive: true }}
      style={{ width: '100%', height: 320 }}
      useResizeHandler
    />
  )
}
