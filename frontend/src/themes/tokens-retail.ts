/**
 * Retail theme — iOS 简约淡雅 (替代 Perplexity-inspired 旧版).
 * 走 chat 主路径(/chat/* + 默认所有 non-banking route).
 */

import { theme } from 'antd';
import type { ThemeConfig } from 'antd';
import { baseTokens } from './tokens-base';

export const retailTokens = {
  background: {
    primary: '#ffffff',
    secondary: '#f2f2f7',   // iOS systemGroupedBackground
    tertiary: '#f9f9fb',
  },
  text: {
    primary: '#000000',
    secondary: 'rgba(60, 60, 67, 0.6)',
    tertiary: 'rgba(60, 60, 67, 0.3)',
  },
  border: {
    base: 'rgba(60, 60, 67, 0.12)',
    strong: '#e5e5ea',
  },
  accent: {
    primary: '#007aff',   // iOS systemBlue
    hover: '#006fe6',
    soft: '#e8f1ff',
  },
  numFontFamily: baseTokens.fontFamily.mono,
} as const;

export const retailThemeConfig: ThemeConfig = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: retailTokens.accent.primary,
    colorSuccess: baseTokens.semantic.success,
    colorWarning: baseTokens.semantic.warning,
    colorError: baseTokens.semantic.error,
    colorInfo: retailTokens.accent.primary,
    colorBgContainer: retailTokens.background.primary,
    colorBgLayout: retailTokens.background.secondary,
    colorBgElevated: retailTokens.background.primary,
    colorText: retailTokens.text.primary,
    colorTextSecondary: retailTokens.text.secondary,
    colorTextTertiary: retailTokens.text.tertiary,
    colorBorder: retailTokens.border.base,
    colorBorderSecondary: retailTokens.border.strong,
    fontFamily: baseTokens.fontFamily.sans,
    fontSize: baseTokens.fontSize.sm,
    borderRadius: baseTokens.radius.md,
    borderRadiusLG: baseTokens.radius.lg,
    borderRadiusSM: baseTokens.radius.sm,
  },
  components: {
    Button: {
      borderRadius: baseTokens.radius.sm,
      controlHeight: 36,
      fontWeight: 500,
    },
    Input: {
      borderRadius: baseTokens.radius.sm,
      controlHeight: 36,
    },
    Modal: {
      borderRadiusLG: baseTokens.radius.lg,
    },
    Card: {
      colorBgContainer: retailTokens.background.primary,
      borderRadiusLG: baseTokens.radius.lg,
    },
    Tag: {
      borderRadiusSM: baseTokens.radius.sm,
    },
    List: {
      itemPadding: '10px 12px',
    },
  },
};
