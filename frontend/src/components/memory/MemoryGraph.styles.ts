/**
 * MemoryGraph styling constants + shared types (Plan 7B Task 2).
 *
 * 7 entity types → fixed colors, 11 rel types → 中文 label,
 * bi-temporal status → line style.
 */
import type { MemoryEdge, MemoryNode } from '@/types/memory'

/** entity_type → background color (spec § 9 视图 1). */
export const ENTITY_COLORS: Record<string, string> = {
  User: '#1890ff', // 蓝 - 自己
  Stock: '#52c41a', // 绿 - 持仓 / 标的
  Industry: '#fa8c16', // 橙 - 申万行业
  Sector: '#faad14', // 黄 - 概念板块
  Metric: '#722ed1', // 紫 - 指标
  Strategy: '#eb2f96', // 粉 - 策略
  Concept: '#13c2c2', // 青 - 抽象概念
}

export const ENTITY_FALLBACK_COLOR = '#d9d9d9'

/** rel_type → 中文 label for hover tooltip / drawer (契约 § 8). */
export const REL_TYPE_LABELS: Record<string, string> = {
  HOLDS: '持仓',
  WATCHES: '关注',
  PREFERS: '偏好',
  AVOIDS: '回避',
  EXPRESSED_VIEW: '表态',
  SOLD: '卖出',
  STUDIED: '研究',
  COMPARED: '对比',
  BELONGS_TO: '属于',
  HAS_CONCEPT: '含概念',
  CORRELATED_WITH: '相关',
}

/** Bi-temporal edge status visual encoding. */
export type EdgeStatus = 'current' | 'ended' | 'invalidated'

export const EDGE_STYLE_BY_STATUS: Record<
  EdgeStatus,
  { lineStyle: 'solid' | 'dashed' | 'dotted'; color: string; width: number }
> = {
  current: { lineStyle: 'solid', color: '#262626', width: 2 },
  ended: { lineStyle: 'dashed', color: '#8c8c8c', width: 1.5 },
  invalidated: { lineStyle: 'dotted', color: '#bfbfbf', width: 1 },
}

/**
 * Edge augmented with optional invalidated_at — graph endpoint may not return
 * it (per Plan 7A schema), but classifier accepts the field if present.
 */
export interface GraphEdgeLike extends MemoryEdge {
  invalidated_at?: string | null
}

/** Pure: classify edge by bi-temporal fields. */
export function classifyEdgeStatus(edge: GraphEdgeLike): EdgeStatus {
  if (edge.invalidated_at) return 'invalidated'
  if (edge.valid_to) return 'ended'
  return 'current'
}

export type GraphNode = MemoryNode
