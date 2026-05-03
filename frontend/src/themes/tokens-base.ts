/**
 * Base design tokens — shared across banking and retail themes.
 *
 * See docs/design-tokens.md for the design philosophy.
 */

export const baseTokens = {
  // Spacing scale (8px base)
  spacing: {
    xs: 4,
    sm: 8,
    md: 16,
    lg: 24,
    xl: 32,
    xxl: 48,
  },
  // Border radius
  radius: {
    sm: 4,
    md: 8,
    lg: 12,
  },
  // Motion durations (ms)
  motion: {
    fast: 150,
    base: 250,
    slow: 400,
  },
  // Font stack
  fontFamily: {
    sans: '-apple-system, "Helvetica Neue", "PingFang SC", "Microsoft YaHei", sans-serif',
    mono: '"SF Mono", "JetBrains Mono", "Cascadia Code", Consolas, monospace',
  },
  // Font sizes
  fontSize: {
    xs: 12,
    sm: 14,
    base: 16,
    lg: 18,
    xl: 24,
    xxl: 32,
  },
  // Semantic colors (shared)
  semantic: {
    success: '#52c41a',
    warning: '#faad14',
    error: '#f5222d',
    info: '#1890ff',
    // 涨跌专用 (中国标准: 红涨绿跌)
    up: '#f5222d',
    down: '#52c41a',
  },
} as const;

export type BaseTokens = typeof baseTokens;
