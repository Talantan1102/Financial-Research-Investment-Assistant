/**
 * frontend/src/api/portfolio.ts
 *
 * Client for the v1.0 /portfolio endpoints.
 * Router prefix = "/portfolio" on backend (no /api/v0 prefix).
 *
 * Live endpoints confirmed in portfolio_router.py:
 *   GET  /portfolio/positions           → PositionRead[]
 *   POST /portfolio/trades              → TradeRead (create single trade)
 *   POST /portfolio/onboarding          → OnboardingResponse
 *
 * TODO: GET /portfolio/trades list endpoint is not yet implemented in backend.
 *       When added, wire it here and display in PortfolioPage.
 */

import { request } from './request'

export type TradeType = 'initial' | 'buy' | 'sell'

export interface PositionRead {
  id: string
  ts_code: string
  name: string
  quantity: number
  /** Decimal as string from backend */
  avg_cost: string
  total_cost: string
  realized_pnl: string
  last_quote_price: string | null
  last_quote_at: string | null
  is_silenced: boolean
}

export function listPositions() {
  return request.get<PositionRead[]>('/portfolio/positions')
}
