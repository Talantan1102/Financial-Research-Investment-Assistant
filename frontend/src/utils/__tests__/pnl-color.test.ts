import { describe, it, expect } from 'vitest'
import { pnlColor } from '../pnl-color'

describe('pnlColor 红涨绿跌', () => {
  it('涨为红', () => expect(pnlColor(1.2)).toBe('#ff3b30'))
  it('跌为绿', () => expect(pnlColor(-0.8)).toBe('#34c759'))
  it('平为中性', () => expect(pnlColor(0)).toBe('inherit'))
})
