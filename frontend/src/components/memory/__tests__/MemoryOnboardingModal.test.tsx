/**
 * MemoryOnboardingModal vitest (Plan 7B Task 5) — 3 项.
 *
 * 首次访问 800ms 后弹 / 已 seen 不弹 / 我知道了 → 标记 seen + close.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import MemoryOnboardingModal, {
  hasSeenOnboarding,
  markOnboardingSeen,
} from '@/components/memory/MemoryOnboardingModal'

const renderWithRouter = () =>
  render(
    <MemoryRouter>
      <MemoryOnboardingModal />
    </MemoryRouter>,
  )

// 不用 fakeTimers, 改用真 setTimeout: 测试用 waitFor 等 800ms 后状态翻转,
// fake timer + react act 与 waitFor 微任务调度组合在 Vitest+React 19 下偶发死锁.
// real timer 多 800ms 等待可接受 (3 项总开销 < 3s).

describe('<MemoryOnboardingModal>', () => {
  beforeEach(() => {
    localStorage.clear()
  })
  afterEach(() => {
    localStorage.clear()
  })

  it('opens modal ~800ms after first mount when no localStorage flag', async () => {
    renderWithRouter()
    expect(screen.queryByText(/我会记住您的投资偏好和持仓/)).toBeNull()
    await waitFor(
      () =>
        expect(screen.getByText(/我会记住您的投资偏好和持仓/)).toBeTruthy(),
      { timeout: 2000 },
    )
  })

  it('does not open when seen flag is already set', async () => {
    markOnboardingSeen()
    renderWithRouter()
    // 等 1000ms 仍不应该出现 modal
    await new Promise((r) => setTimeout(r, 1000))
    expect(screen.queryByText(/我会记住您的投资偏好/)).toBeNull()
    expect(hasSeenOnboarding()).toBe(true)
  })

  it("clicking 我知道了 marks seen and closes modal", async () => {
    renderWithRouter()
    await waitFor(() => screen.getByTestId('onboarding-confirm'), {
      timeout: 2000,
    })
    fireEvent.click(screen.getByTestId('onboarding-confirm'))
    expect(hasSeenOnboarding()).toBe(true)
  })
})
