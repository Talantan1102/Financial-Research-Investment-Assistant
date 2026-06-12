import { baseTokens } from '@/themes/tokens-base'

/**
 * Returns a CSS color string for a profit/loss value using Chinese market convention:
 * 红涨(red=up) / 绿跌(green=down) / inherit for zero.
 */
export function pnlColor(n: number): string {
  if (n > 0) return baseTokens.semantic.up    // #ff3b30 红=涨
  if (n < 0) return baseTokens.semantic.down  // #34c759 绿=跌
  return 'inherit'
}
