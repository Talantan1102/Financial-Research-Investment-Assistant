/**
 * frontend/src/types/research.ts
 * Mirrors backend Pydantic schemas in app.agents.schemas + app.agents.investment_dd_schema.
 */

// ── Enum types (mirror backend Literal types) ────────────────────────────────

export type InvestmentObjective =
  | 'capital_preservation'
  | 'stable_growth'
  | 'balanced'
  | 'aggressive_growth'

export type InvestmentHorizon = 'short_term' | 'medium_term' | 'long_term'

export type RiskTolerance =
  | 'conservative'
  | 'moderate'
  | 'balanced'
  | 'aggressive'
  | 'very_aggressive'

export type Recommendation =
  | 'recommend_buy'
  | 'recommend_overweight'
  | 'recommend_hold'
  | 'recommend_underweight'
  | 'recommend_sell'

export type RiskSeverity = 'low' | 'medium' | 'high'

export type OverallRiskLevel = 'low' | 'medium' | 'high' | 'very_high'

// ── Request schema (mirrors ResearchRequest in app.agents.schemas) ────────────

export interface ResearchRequest {
  target_ts_code: string
  client_total_aum: number
  client_existing_position?: number
  investment_objective: InvestmentObjective
  investment_horizon: InvestmentHorizon
  risk_tolerance: RiskTolerance
  user_message?: string
}

// ── Report sub-schemas (mirrors investment_dd_schema.py) ──────────────────────

export interface PriceRange {
  low: number
  high: number
}

export interface FinancialMetric {
  name: string
  value: string
  period: string
  yoy_change: string | null
}

export interface RiskItem {
  title: string
  description: string
  severity: RiskSeverity
  mitigations: string[]
}

export interface ValuationAnalysis {
  narrative: string
  pe_historical_percentile: string | null
  dcf_valuation: string | null
  peer_comparison: string | null
}

export interface TargetOverview {
  narrative: string
  registered_capital: string | null
  main_business: string
  controlling_shareholder: string | null
  listing_status: string | null
  current_pe: number | null
  current_pb: number | null
  current_market_cap: number | null
  dividend_yield: number | null
  evidence: string[]
}

export interface LegalQualification {
  narrative: string
  legal_status: string
  business_qualifications: string[]
  adverse_records: string[]
  evidence: string[]
}

export interface FinancialAnalysis {
  narrative: string
  key_metrics: FinancialMetric[]
  profitability_analysis: string
  growth_analysis: string
  return_analysis: string
  cash_flow_analysis: string
  valuation_analysis: ValuationAnalysis
  year_over_year_summary: string | null
  evidence: string[]
}

export interface IndustryAnalysis {
  narrative: string
  industry_name: string
  industry_outlook: string
  competitive_position: string
  key_competitors: string[]
  policy_impact: string
  evidence: string[]
}

export interface RiskAssessment {
  narrative: string
  market_risk: RiskItem[]
  growth_risk: RiskItem[]
  event_risk: RiskItem[]
  valuation_risk: RiskItem[]
  overall_risk_level: OverallRiskLevel
  evidence: string[]
}

export interface InvestmentRecommendation {
  narrative: string
  recommendation: Recommendation
  recommended_position_size_pct: number
  recommended_holding_period: InvestmentHorizon
  recommended_entry_price_range: PriceRange
  recommended_stop_loss_price: number
  estimated_target_price_range: PriceRange
  position_management_conditions: string[]
  evidence: string[]
}

// ── Main report (mirrors InvestmentDueDiligenceReport) ────────────────────────

export interface InvestmentDueDiligenceReport {
  target_name: string
  target_ts_code: string
  request_id: string
  generated_at: string // ISO datetime string
  target_close_price_at_gen: number | null
  target_market_cap_at_gen: number | null
  target_overview: TargetOverview
  legal_qualification: LegalQualification
  financial_analysis: FinancialAnalysis
  industry_analysis: IndustryAnalysis
  risk_assessment: RiskAssessment
  investment_recommendation: InvestmentRecommendation
  disclaimer: string
}

// ── SSE event (mirrors ResearchStreamEvent in router/research.py) ─────────────

export interface SSEResearchEvent {
  type:
    | 'plan'
    | 'data_progress'
    | 'insight'
    | 'report_chunk'
    | 'critic_score'
    | 'done'
    | 'error'
  data: Record<string, unknown> // narrowed by Task 6 consumers
}

// ── Chinese i18n labels ───────────────────────────────────────────────────────

export const INVESTMENT_OBJECTIVE_LABELS: Record<InvestmentObjective, string> = {
  capital_preservation: '保本增值',
  stable_growth: '稳健增长',
  balanced: '平衡型',
  aggressive_growth: '高成长',
}

export const INVESTMENT_HORIZON_LABELS: Record<InvestmentHorizon, string> = {
  short_term: '短期（< 6 个月）',
  medium_term: '中期（6–24 个月）',
  long_term: '长期（> 24 个月）',
}

export const RISK_TOLERANCE_LABELS: Record<RiskTolerance, string> = {
  conservative: '保守型',
  moderate: '稳健型',
  balanced: '平衡型',
  aggressive: '进取型',
  very_aggressive: '激进型',
}

export const RECOMMENDATION_LABELS: Record<Recommendation, string> = {
  recommend_buy: '买入',
  recommend_overweight: '增持',
  recommend_hold: '持有',
  recommend_underweight: '减持',
  recommend_sell: '卖出',
}

export const RISK_LEVEL_LABELS: Record<OverallRiskLevel, string> = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
  very_high: '极高风险',
}
