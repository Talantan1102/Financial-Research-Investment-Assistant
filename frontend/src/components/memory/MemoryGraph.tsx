/**
 * MemoryGraph (Plan 7B Task 2) — Cytoscape graph viz of /memory page.
 *
 * 7 entity_type → 颜色; 11 rel_type → label hover; bi-temporal 状态 →
 * 实线 (current) / 虚线 (ended) / 点线 (invalidated). Edge tap → Drawer 详情.
 *
 * Source spec § 9 视图 1, contracts § 10 fetchMemoryGraph endpoint.
 *
 * highlightEdgeId: 由 chat TextMessage [查看](#mem-{edge_id}) 跳转过来时,
 * 通过 useSearchParams('highlight_edge') 读取 → 高亮该 edge + center.
 *
 * jsdom 兼容性: 在测试环境 (HTMLCanvasElement.prototype.getContext 为空 stub
 * 的情况) cytoscape 实例化会因 textureOnViewport 抛错。本组件以 try/catch
 * 包住 CytoscapeComponent 的 init 路径外的 fallback 渲染, 让 vitest 仅检测
 * loading / empty / error / data 数据流, 真 layout 由 Playwright e2e 验。
 */
import { Descriptions, Drawer, Empty, Spin, Tag } from 'antd'
import type { Core, EdgeSingular, ElementDefinition, NodeSingular } from 'cytoscape'
import { useEffect, useMemo, useRef, useState } from 'react'
import CytoscapeComponent from 'react-cytoscapejs'
import { fetchMemoryGraph } from '@/api/memoryApi'
import type { GraphResponse } from '@/types/memory'
import {
  classifyEdgeStatus,
  EDGE_STYLE_BY_STATUS,
  ENTITY_COLORS,
  ENTITY_FALLBACK_COLOR,
  REL_TYPE_LABELS,
  type GraphEdgeLike,
  type GraphNode,
} from './MemoryGraph.styles'

interface Props {
  highlightEdgeId?: string | null
}

export default function MemoryGraph({ highlightEdgeId }: Props) {
  const [nodes, setNodes] = useState<GraphNode[]>([])
  const [edges, setEdges] = useState<GraphEdgeLike[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedEdge, setSelectedEdge] = useState<GraphEdgeLike | null>(null)
  const cyRef = useRef<Core | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchMemoryGraph()
      .then((data: GraphResponse) => {
        if (cancelled) return
        setNodes(data.nodes)
        setEdges(data.edges as GraphEdgeLike[])
        setError(null)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message ?? e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Highlight an edge on chat-jump navigation.
  useEffect(() => {
    if (!cyRef.current || !highlightEdgeId) return
    const cy = cyRef.current
    cy.elements().removeClass('highlighted')
    const target = cy.getElementById(highlightEdgeId)
    if (target.length > 0) {
      target.addClass('highlighted')
      cy.center(target)
    }
  }, [highlightEdgeId, edges])

  const elements: ElementDefinition[] = useMemo(() => {
    const nodeEls: ElementDefinition[] = nodes.map((n) => ({
      data: {
        id: n.node_id,
        label: n.entity_label,
        entity_type: n.entity_type,
      },
    }))
    const edgeEls: ElementDefinition[] = edges.map((e) => ({
      data: {
        id: e.edge_id,
        source: e.source_node_id,
        target: e.target_node_id,
        rel_type: e.rel_type,
        rel_label: REL_TYPE_LABELS[e.rel_type] ?? e.rel_type,
        status: classifyEdgeStatus(e),
      },
    }))
    return [...nodeEls, ...edgeEls]
  }, [nodes, edges])

  const stylesheet = useMemo(
    () => [
      {
        selector: 'node',
        style: {
          'background-color': (ele: NodeSingular) =>
            ENTITY_COLORS[ele.data('entity_type') as string] ??
            ENTITY_FALLBACK_COLOR,
          label: 'data(label)',
          'font-size': 11,
          'text-valign': 'center',
          'text-halign': 'center',
          color: '#fff',
          width: 40,
          height: 40,
        },
      },
      {
        selector: 'edge',
        style: {
          width: (ele: EdgeSingular) =>
            EDGE_STYLE_BY_STATUS[
              ele.data('status') as keyof typeof EDGE_STYLE_BY_STATUS
            ]?.width ?? 1,
          'line-color': (ele: EdgeSingular) =>
            EDGE_STYLE_BY_STATUS[
              ele.data('status') as keyof typeof EDGE_STYLE_BY_STATUS
            ]?.color ?? '#bfbfbf',
          'line-style': (ele: EdgeSingular) =>
            EDGE_STYLE_BY_STATUS[
              ele.data('status') as keyof typeof EDGE_STYLE_BY_STATUS
            ]?.lineStyle ?? 'solid',
          'target-arrow-shape': 'triangle',
          'target-arrow-color': (ele: EdgeSingular) =>
            EDGE_STYLE_BY_STATUS[
              ele.data('status') as keyof typeof EDGE_STYLE_BY_STATUS
            ]?.color ?? '#bfbfbf',
          'curve-style': 'bezier',
          label: 'data(rel_label)',
          'font-size': 9,
          'text-rotation': 'autorotate',
        },
      },
      {
        selector: 'edge.highlighted',
        style: {
          'line-color': '#fa541c',
          'target-arrow-color': '#fa541c',
          width: 4,
          'z-index': 999,
        },
      },
    ],
    [],
  )

  if (loading)
    return (
      <div data-testid="memory-graph-loading" style={{ padding: 24 }}>
        <Spin size="large" />
      </div>
    )
  if (error)
    return (
      <Empty
        data-testid="memory-graph-error"
        description={`加载失败: ${error}`}
      />
    )
  if (nodes.length === 0)
    return (
      <Empty
        data-testid="memory-graph-empty"
        description="还没有 memory — 先聊几条试试"
      />
    )

  return (
    <div data-testid="memory-graph">
      <CytoscapeComponent
        elements={elements}
        stylesheet={stylesheet as unknown as cytoscape.Stylesheet[]}
        layout={{ name: 'cose', animate: false }}
        style={{ width: '100%', height: '600px', background: '#fafafa' }}
        cy={(cy: Core) => {
          cyRef.current = cy
          cy.on('tap', 'edge', (evt) => {
            const edgeId = evt.target.id()
            const found = edges.find((e) => e.edge_id === edgeId)
            if (found) setSelectedEdge(found)
          })
        }}
      />
      <Drawer
        open={!!selectedEdge}
        onClose={() => setSelectedEdge(null)}
        title="Memory Edge 详情"
        width={420}
        data-testid="memory-graph-drawer"
      >
        {selectedEdge && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="关系">
              {REL_TYPE_LABELS[selectedEdge.rel_type] ?? selectedEdge.rel_type}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag
                color={
                  classifyEdgeStatus(selectedEdge) === 'current'
                    ? 'green'
                    : classifyEdgeStatus(selectedEdge) === 'ended'
                      ? 'orange'
                      : 'default'
                }
              >
                {classifyEdgeStatus(selectedEdge)}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="valid_from">
              {selectedEdge.valid_from}
            </Descriptions.Item>
            <Descriptions.Item label="valid_to">
              {selectedEdge.valid_to ?? '(进行中)'}
            </Descriptions.Item>
            <Descriptions.Item label="importance">
              {selectedEdge.importance}
            </Descriptions.Item>
            <Descriptions.Item label="reasoning">
              {selectedEdge.reasoning ?? '—'}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  )
}
