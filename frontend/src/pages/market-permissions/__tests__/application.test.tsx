import { renderWithProviders } from '@/test-utils/render'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  cancelApplication: vi.fn(),
  confirmApplication: vi.fn(),
  getMarketPermissions: vi.fn(),
  startApplication: vi.fn(),
  submitApplicationProfile: vi.fn(),
}))

vi.mock('@/api/investorSuitability', () => api)

import PermissionApplicationPage from '../application'

describe('PermissionApplicationPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getMarketPermissions.mockResolvedValue([
      {
        entitlement_id: 'entitlement-main',
        market: 'main',
        status: 'not_applied',
        can_buy: false,
        can_sell: false,
        can_subscribe: false,
        rule_version: null,
        enabled_at: null,
        restricted_at: null,
      },
      {
        entitlement_id: 'entitlement-star',
        market: 'star',
        status: 'not_applied',
        can_buy: false,
        can_sell: false,
        can_subscribe: false,
        rule_version: null,
        enabled_at: null,
        restricted_at: null,
      },
    ])
    api.startApplication.mockResolvedValue({
      application_id: 'application-star',
      market: 'star',
      status: 'awaiting_information',
      assessment_id: null,
      started_at: '2026-07-27T00:00:00Z',
      completed_at: null,
    })
    api.submitApplicationProfile.mockResolvedValue({
      assessment_id: 'assessment-star',
      market: 'star',
      decision: 'passed',
      failed_conditions: null,
      rule_version: 'a-share-2026-07-27',
      disclosure_version: 'star-2026-01',
    })
    api.cancelApplication.mockResolvedValue({
      application_id: 'application-star',
      market: 'star',
      status: 'cancelled_by_user',
      assessment_id: 'assessment-star',
      started_at: '2026-07-27T00:00:00Z',
      completed_at: '2026-07-27T00:01:00Z',
    })
  })

  it('lets the user cancel at the disclosure step without enabling permission', async () => {
    const user = userEvent.setup()
    renderWithProviders(<PermissionApplicationPage market="star" />)

    await user.type(
      await screen.findByLabelText('最近 20 个交易日日均证券资产'),
      '600000',
    )
    await user.type(screen.getByLabelText('证券交易经验月数'), '36')
    await user.selectOptions(screen.getByLabelText('风险等级'), 'C4')
    await user.click(screen.getByRole('button', { name: '检查开通条件' }))

    expect(await screen.findByText('风险揭示书')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '取消申请' }))

    expect(api.cancelApplication).toHaveBeenCalledWith('application-star')
    expect(api.confirmApplication).not.toHaveBeenCalled()
    expect(await screen.findByText('申请已取消')).toBeInTheDocument()
  })
})
