export type OrderSide = 'buy' | 'sell'
export type OrderType = 'market' | 'limit'

export interface PaperOrderDraft {
  side: OrderSide
  ts_code: string
  name: string
  quantity: number
  order_type: OrderType
  limit_price: string | null
}

export interface PaperQuoteLevel {
  price: string
  quantity: number
}

export interface PaperOrderPreview {
  draft: PaperOrderDraft
  quote: {
    ts_code: string
    name: string
    quoted_at?: string
    previous_close?: string
    last_price?: string
    bids?: PaperQuoteLevel[]
    asks?: PaperQuoteLevel[]
    source: string
    suspended?: boolean
    [key: string]: unknown
  }
  estimated_gross: string
  estimated_fees: {
    commission: string
    stamp_duty: string
    transfer_fee: string
    total?: string
  }
  estimated_cash_required: string
  available_cash: string
  sellable_quantity: number
  market_phase: string
  rules_version: string
}

export interface PaperOrderPreviewRequest {
  draft: PaperOrderDraft
}

export interface ApprovalToolCall {
  id: string
  name: string
  arguments: string | Record<string, unknown>
}

export interface EditableApprovalRequest extends Record<string, unknown> {
  tool_calls: ApprovalToolCall[]
  editable_tool_call_ids?: string[]
}

export interface ApprovalResumeResponse {
  approved: boolean
  text?: string
  edited_arguments?: Record<string, Record<string, unknown>>
}

export interface InputResumeResponse {
  text: string
}

export type RunResumeResponse = ApprovalResumeResponse | InputResumeResponse
