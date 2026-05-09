import { describe, expect, it } from 'vitest'
import { computeBackoffMs } from '@/hooks/useExponentialBackoff'

describe('computeBackoffMs', () => {
  it('attempt 0 returns 1000ms', () => {
    expect(computeBackoffMs(0)).toBe(1000)
  })
  it('attempt 1 returns 2000ms', () => {
    expect(computeBackoffMs(1)).toBe(2000)
  })
  it('attempt 2 returns 4000ms', () => {
    expect(computeBackoffMs(2)).toBe(4000)
  })
  it('attempt 3 returns 8000ms', () => {
    expect(computeBackoffMs(3)).toBe(8000)
  })
  it('attempt 4 returns 16000ms', () => {
    expect(computeBackoffMs(4)).toBe(16000)
  })
  it('attempt 5 caps at 30000ms', () => {
    expect(computeBackoffMs(5)).toBe(30000)
  })
  it('attempt 100 still caps at 30000ms', () => {
    expect(computeBackoffMs(100)).toBe(30000)
  })
})
