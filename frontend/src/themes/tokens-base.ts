/**
 * Base design tokens — shared across banking and retail themes.
 * iOS HIG-aligned token values.
 */

export const baseTokens = {
  spacing: {
    xs: 4, sm: 8, md: 16, lg: 24, xl: 32, xxl: 48,
  },
  radius: {
    sm: 8, md: 12, lg: 16,  // iOS HIG 大圆角
  },
  motion: {
    fast: 150, base: 250, slow: 400,
  },
  fontFamily: {
    sans: '-apple-system, "SF Pro Text", "SF Pro Display", "PingFang SC", "Helvetica Neue", system-ui, sans-serif',
    mono: '"SF Mono", ui-monospace, "JetBrains Mono", "Menlo", Consolas, monospace',
  },
  fontSize: {
    xs: 12, sm: 14, base: 15, lg: 17, xl: 22, xxl: 28,
  },
  semantic: {
    success: '#34c759',  // iOS systemGreen
    warning: '#ff9500',  // iOS systemOrange
    error: '#ff3b30',    // iOS systemRed
    info: '#007aff',     // iOS systemBlue
    // 中国市场涨跌(红涨绿跌)— 走 iOS 红绿但保中国惯例
    up: '#ff3b30',
    down: '#34c759',
  },
} as const;

export type BaseTokens = typeof baseTokens;
