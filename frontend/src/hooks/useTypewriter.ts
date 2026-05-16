/**
 * frontend/src/hooks/useTypewriter.ts
 *
 * RAF + char queue 打字机渲染 (Plan 2 Task 6, spec § 6.5)。
 *
 * Why: Plan 2 后端 chunk-level event push (每 50-100 chars 一个 chunk),前端
 * 直接 paste 整 chunk 会显得"跳字";打字机把 chunk 拆成字符,按速率逐字
 * 吐出,视觉等同 token-level 流式。
 *
 * 速率策略:
 * - queue 长度 < catchupThreshold(默认 200 chars) → baseSpeed(默认 30 chars/s)
 * - queue 长度 ≥ catchupThreshold → catchupSpeed(默认 100 chars/s)
 *
 * RAF loop:每帧 (~16ms) 根据 dt + speed 算 `floor(dt * speed)` 个字符吐出。
 * 队列空 → 自动停 RAF,下次 enqueue 重启。unmount 时 cleanup cancelAnimationFrame。
 */

import { useCallback, useEffect, useRef } from 'react'

interface UseTypewriterOptions {
  onChar: (char: string) => void
  baseSpeed?: number // chars/s when queue < catchupThreshold (default 30)
  catchupSpeed?: number // chars/s when queue >= catchupThreshold (default 100)
  catchupThreshold?: number // queue len threshold (default 200)
}

interface UseTypewriter {
  enqueue: (text: string) => void
  flush: () => void // drain everything immediately + cancel RAF
  drained: () => Promise<void> // wait until RAF naturally drains the queue
}

export function useTypewriter(options: UseTypewriterOptions): UseTypewriter {
  const queueRef = useRef<string[]>([])
  const rafRef = useRef<number | null>(null)
  const lastTimeRef = useRef<number>(0)
  const remainderRef = useRef<number>(0) // 累积 dt*speed 的小数部分
  const onCharRef = useRef(options.onChar)
  onCharRef.current = options.onChar

  const baseSpeed = options.baseSpeed ?? 30
  const catchupSpeed = options.catchupSpeed ?? 100
  const catchupThreshold = options.catchupThreshold ?? 200

  const startLoop = useCallback(() => {
    if (rafRef.current !== null) return // already running

    const tick = (timestamp: number) => {
      if (lastTimeRef.current === 0) lastTimeRef.current = timestamp
      const dt = (timestamp - lastTimeRef.current) / 1000
      const speed =
        queueRef.current.length >= catchupThreshold ? catchupSpeed : baseSpeed
      // 累积小数 char 数 — 否则 16ms 帧 + 100 chars/s 永远 floor(1.6)=1,实测
      // 60 chars/s 远低于配置的 catchupSpeed。
      const want = dt * speed + remainderRef.current
      const charsToYield = Math.max(1, Math.floor(want))
      remainderRef.current = want - charsToYield
      for (let i = 0; i < charsToYield && queueRef.current.length > 0; i++) {
        const ch = queueRef.current.shift()
        if (ch !== undefined) onCharRef.current(ch)
      }
      lastTimeRef.current = timestamp
      if (queueRef.current.length > 0) {
        rafRef.current = requestAnimationFrame(tick)
      } else {
        rafRef.current = null
        lastTimeRef.current = 0
        remainderRef.current = 0
      }
    }
    rafRef.current = requestAnimationFrame(tick)
  }, [baseSpeed, catchupSpeed, catchupThreshold])

  const enqueue = useCallback(
    (text: string) => {
      if (!text) return
      // split('') is OK for ASCII;for multi-byte (CJK,emoji) we still split by
      // code unit — 每帧多吐几个 code unit 视觉上仍是逐字效果,且 token 通常
      // 已是单字符级,不存在拆字问题。
      queueRef.current.push(...text.split(''))
      startLoop()
    },
    [startLoop],
  )

  const flush = useCallback(() => {
    while (queueRef.current.length > 0) {
      const ch = queueRef.current.shift()
      if (ch !== undefined) onCharRef.current(ch)
    }
    if (rafRef.current !== null) {
      if (typeof cancelAnimationFrame === 'function') {
        cancelAnimationFrame(rafRef.current)
      }
      rafRef.current = null
      lastTimeRef.current = 0
      remainderRef.current = 0
    }
  }, [])

  const drained = useCallback((): Promise<void> => {
    return new Promise((resolve) => {
      const check = () => {
        if (queueRef.current.length === 0 && rafRef.current === null) {
          resolve()
        } else {
          // 用 setTimeout 而非 RAF — drained 的 caller 可能在 RAF 已停的情况
          // 下被调用(比如 done event 紧跟在 token event 之后,queue 立刻有 chars
          // 但 RAF 还没有时间触发 startLoop)。每 ~16ms 轮一次,RAF loop 在
          // 推完前不会 resolve。
          setTimeout(check, 16)
        }
      }
      check()
    })
  }, [])

  useEffect(() => {
    return () => {
      if (rafRef.current !== null && typeof cancelAnimationFrame === 'function') {
        cancelAnimationFrame(rafRef.current)
      }
    }
  }, [])

  return { enqueue, flush, drained }
}
