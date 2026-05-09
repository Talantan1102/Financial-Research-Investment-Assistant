import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useScrollStick } from '@/components/chat/useScrollStick'

describe('useScrollStick', () => {
  it('returns isAtBottom=true initially; toggles false when sentinel exits viewport', () => {
    let cb: ((entries: { isIntersecting: boolean }[]) => void) | null = null
    class IO {
      constructor(c: (entries: { isIntersecting: boolean }[]) => void) {
        cb = c
      }
      observe = vi.fn()
      disconnect = vi.fn()
      unobserve = vi.fn()
      takeRecords = vi.fn(() => [])
      root = null
      rootMargin = ''
      thresholds: number[] = []
    }
    const orig = globalThis.IntersectionObserver
    // @ts-expect-error jsdom shim
    globalThis.IntersectionObserver = IO
    try {
      const sentinelEl = document.createElement('div')
      const { result } = renderHook(() => useScrollStick(sentinelEl))
      expect(result.current.isAtBottom).toBe(true)
      act(() => cb?.([{ isIntersecting: false }]))
      expect(result.current.isAtBottom).toBe(false)
    } finally {
      globalThis.IntersectionObserver = orig
    }
  })

  it('scrollToBottom() invokes sentinel.scrollIntoView', () => {
    class IO {
      constructor() {}
      observe = vi.fn()
      disconnect = vi.fn()
      unobserve = vi.fn()
      takeRecords = vi.fn(() => [])
      root = null
      rootMargin = ''
      thresholds: number[] = []
    }
    const orig = globalThis.IntersectionObserver
    // @ts-expect-error jsdom shim
    globalThis.IntersectionObserver = IO
    try {
      const el = document.createElement('div')
      el.scrollIntoView = vi.fn()
      const { result } = renderHook(() => useScrollStick(el))
      act(() => result.current.scrollToBottom())
      expect(el.scrollIntoView).toHaveBeenCalled()
    } finally {
      globalThis.IntersectionObserver = orig
    }
  })
})
