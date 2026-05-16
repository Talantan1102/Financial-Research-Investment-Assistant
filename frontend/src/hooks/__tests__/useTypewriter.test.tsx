/**
 * frontend/src/hooks/__tests__/useTypewriter.test.tsx
 *
 * Plan 2 Task 6 — RAF + char queue 打字机 hook 单元测试。
 *
 * 用 vitest fake timer 推进 setTimeout — 我们把 requestAnimationFrame 桩到
 * setTimeout(cb, 16) 上,这样 fake timer 推进就能驱动 RAF loop。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useTypewriter } from '../useTypewriter'

describe('useTypewriter — RAF char queue', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    let id = 0
    // RAF stub: schedule cb via setTimeout(16ms) so fake timer can drive it.
    // timestamp arg passed to cb is current performance.now().
    globalThis.requestAnimationFrame = ((cb: FrameRequestCallback): number => {
      id += 1
      setTimeout(() => cb(performance.now()), 16)
      return id
    }) as typeof globalThis.requestAnimationFrame
    globalThis.cancelAnimationFrame = vi.fn() as typeof globalThis.cancelAnimationFrame
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('enqueues text and yields all chars when timer is advanced enough', async () => {
    const yielded: string[] = []
    const { result } = renderHook(() =>
      useTypewriter({ onChar: (ch) => yielded.push(ch) }),
    )

    act(() => {
      result.current.enqueue('hello')
    })
    // Advance 1s — base speed 30 chars/s, queue=5, should fully drain.
    await act(async () => {
      vi.advanceTimersByTime(1000)
    })
    expect(yielded.join('')).toBe('hello')
  })

  it('catches up faster when queue exceeds catchupThreshold', async () => {
    const yielded: string[] = []
    const { result } = renderHook(() =>
      useTypewriter({
        onChar: (ch) => yielded.push(ch),
        baseSpeed: 30,
        catchupSpeed: 100,
        catchupThreshold: 200,
      }),
    )

    act(() => {
      // 250 chars — past threshold, should use catchupSpeed=100 chars/s
      result.current.enqueue('x'.repeat(250))
    })
    // Advance 1s — at 100 chars/s should yield ~100 chars.
    // We allow >=80 to tolerate RAF tick discreteness (16ms granularity).
    await act(async () => {
      vi.advanceTimersByTime(1000)
    })
    expect(yielded.length).toBeGreaterThanOrEqual(80)
  })

  it('concatenates multiple enqueues into a single queue', async () => {
    const yielded: string[] = []
    const { result } = renderHook(() =>
      useTypewriter({ onChar: (ch) => yielded.push(ch) }),
    )

    act(() => {
      result.current.enqueue('ab')
      result.current.enqueue('cd')
    })
    await act(async () => {
      vi.advanceTimersByTime(1000)
    })
    expect(yielded.join('')).toBe('abcd')
  })

  it('flush() drains everything immediately + cancels pending RAF', () => {
    const yielded: string[] = []
    const { result } = renderHook(() =>
      useTypewriter({ onChar: (ch) => yielded.push(ch) }),
    )

    act(() => {
      result.current.enqueue('xyz')
      result.current.flush()
    })
    expect(yielded.join('')).toBe('xyz')
  })
})
