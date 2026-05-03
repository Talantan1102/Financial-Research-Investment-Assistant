/**
 * Retail theme — Perplexity-inspired light modern style.
 * For C-1 个股研究 / C-2 自选股 / C-3 NL 选股 / 通用对话 entries.
 */

import { theme } from 'antd';
import type { ThemeConfig } from 'antd';
import { baseTokens } from './tokens-base';

export const retailTokens = {
  background: {
    primary: '#ffffff',
    secondary: '#f7f8fa',
    tertiary: '#eef0f3',
  },
  text: {
    primary: '#1a1d21',
    secondary: '#5d6975',
    tertiary: '#8a96a3',
  },
  border: {
    base: '#e5e8eb',
    strong: '#c9cfd5',
  },
  accent: {
    primary: '#1890ff',
    hover: '#40a9ff',
  },
  numFontFamily: baseTokens.fontFamily.sans,
} as const;

export const retailThemeConfig: ThemeConfig = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: retailTokens.accent.primary,
    colorBgContainer: retailTokens.background.primary,
    colorBgLayout: retailTokens.background.secondary,
    colorText: retailTokens.text.primary,
    colorTextSecondary: retailTokens.text.secondary,
    colorBorder: retailTokens.border.base,
    fontFamily: baseTokens.fontFamily.sans,
    borderRadius: baseTokens.radius.md,
  },
  components: {
    Card: {
      colorBgContainer: retailTokens.background.primary,
      borderRadiusLG: baseTokens.radius.lg,
    },
  },
};
