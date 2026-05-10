// C.5 cross-session memory — frontend types
// 严格对应 backend/app/router/memory_router.py Pydantic schemas (契约 § 10).

export type EntityType =
  | 'User'
  | 'Stock'
  | 'Industry'
  | 'Sector'
  | 'Metric'
  | 'Strategy'
  | 'Concept'

export interface MemoryNode {
  node_id: string
  entity_type: EntityType
  entity_label: string
  properties: Record<string, unknown>
}

export interface MemoryEdge {
  edge_id: string
  source_node_id: string
  target_node_id: string
  rel_type: string
  valid_from: string // ISO 8601
  valid_to: string | null
  importance: 0.2 | 0.5 | 0.9
  reasoning: string | null
}

export interface GraphResponse {
  nodes: MemoryNode[]
  edges: MemoryEdge[]
}

export interface TimelineEdge {
  edge_id: string
  rel_type: string
  source_label: string
  target_label: string
  valid_from: string
  valid_to: string | null
  importance: number
  invalidated_at: string | null
}

export interface TimelineResponse {
  items: TimelineEdge[]
  total: number
  page: number
  page_size: number
}

export interface AuditEdge {
  edge_id: string
  rel_type: string
  source_label: string
  target_label: string
  invalidated_at: string
  invalidated_by_edge_id: string | null
  original_reasoning: string | null
}

export interface AuditResponse {
  items: AuditEdge[]
  total: number
}

export type WorkingBlockName = 'persona' | 'scratchpad'

export interface WorkingBlock {
  block_name: WorkingBlockName
  content: string
  token_count: number
  max_tokens: number
  updated_at: string
}

export interface BlocksResponse {
  blocks: WorkingBlock[]
}

export interface InvalidateResponse {
  edge_id: string
  invalidated_at: string
  status: 'invalidated'
}

export interface TimelineFilters {
  rel_type?: string
  entity_label?: string
  page?: number
  page_size?: number
}
