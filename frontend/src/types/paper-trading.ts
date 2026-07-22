export type OrderSide = 'buy' | 'sell'
export type OrderType = 'market' | 'limit'
export type OrderStatus =
  | 'awaiting_confirmation'
  | 'queued'
  | 'open'
  | 'partially_filled'
  | 'filled'
  | 'cancelled'
  | 'expired'
  | 'rejected'

export interface OrderDraft {
  side: OrderSide
  ts_code: string
  name: string
  quantity: number
  order_type: OrderType
  limit_price: string | null
}

export interface QuoteSnapshot {
  price: string
  timestamp?: string
  source?: string
  [key: string]: unknown
}

export interface OrderPreview {
  order_id: string
  draft: OrderDraft
  quote: QuoteSnapshot
  estimated_gross: string
  estimated_fees: Record<string, string>
  estimated_cash_required: string
  available_cash: string
  sellable_quantity: number
  market_phase: string
  rules_version: string
}

export interface PaperAccount {
  id: string
  generation: number
  initial_cash: string
  available_cash: string
  frozen_cash: string
  status: string
}

export interface PaperOrder {
  id: string
  account_generation: number
  ts_code: string
  name: string
  side: OrderSide
  order_type: OrderType
  quantity: number
  limit_price: string | null
  filled_quantity: number
  avg_fill_price: string | null
  reserved_cash: string
  reserved_quantity: number
  status: OrderStatus
  original_proposal: Record<string, unknown>
  confirmed_payload: Record<string, unknown> | null
  user_edits: Record<string, unknown> | null
  quote_snapshot: Record<string, unknown>
  rules_version: string
  reject_code: string | null
  reject_message: string | null
  expires_at: string
  created_at: string
  confirmed_at: string | null
  completed_at: string | null
}

export interface CancelPreview {
  order_id: string
  status: OrderStatus
  filled_quantity: number
  remaining_quantity: number
  reserved_cash: string
  reserved_quantity: number
}

export interface ResetPreview {
  account_id: string
  generation: number
  current_initial_cash: string
  replacement_initial_cash: string
}

export type ApprovalType = 'paper_order' | 'paper_cancel' | 'paper_reset'

export interface ApprovalPayload {
  approval_id: string
  approval_type: ApprovalType
  resource_id: string
  proposal: OrderDraft | Record<string, unknown>
  preview: OrderPreview | CancelPreview | ResetPreview
  expires_at: string
}

export interface ApprovalRequestEvent extends ApprovalPayload {
  type: 'approval_request'
  seq: number
}

export type ApprovalCardPhase = 'draft' | 'preview' | 'submitting' | 'error'

export interface ApprovalCardState extends ApprovalPayload {
  phase: ApprovalCardPhase
  error: string | null
}

export interface OrderPreviewRequest {
  draft: OrderDraft
}

export interface OrderConfirmRequest extends OrderPreviewRequest {
  client_request_id: string
}

export type CancelPreviewRequest = never

export interface CancelConfirmRequest {
  confirmation_id: string
}

export interface ResetPreviewRequest {
  initial_cash: string
}

export interface ResetConfirmRequest extends ResetPreviewRequest {
  session_id: string
  confirmation_id: string
}
