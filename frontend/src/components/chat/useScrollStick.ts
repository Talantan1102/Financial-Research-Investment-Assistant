import { useCallback, useEffect, useState } from 'react'

export interface UseScrollStickResult {
  isAtBottom: boolean
  scrollToBottom: () => void
}

/**
 * Auto-stick scroll to bottom via IntersectionObserver. While sentinel is
 * visible (isAtBottom=true), caller may auto-scroll on new messages.
 * When user scrolls up, sentinel exits → isAtBottom=false → stop sticking.
 */
export function useScrollStick(sentinel: Element | null): UseScrollStickResult {
  const [isAtBottom, setIsAtBottom] = useState(true)

  useEffect(() => {
    if (!sentinel) return
    const obs = new IntersectionObserver(
      (entries) => setIsAtBottom(entries[0]?.isIntersecting ?? false),
      { threshold: 0.01 },
    )
    obs.observe(sentinel)
    return () => obs.disconnect()
  }, [sentinel])

  const scrollToBottom = useCallback(() => {
    if (!sentinel) return
    if (typeof (sentinel as Element & { scrollIntoView?: () => void }).scrollIntoView === 'function') {
      ;(sentinel as Element & { scrollIntoView: (opts?: ScrollIntoViewOptions) => void }).scrollIntoView({
        behavior: 'smooth',
        block: 'end',
      })
    }
  }, [sentinel])

  return { isAtBottom, scrollToBottom }
}
