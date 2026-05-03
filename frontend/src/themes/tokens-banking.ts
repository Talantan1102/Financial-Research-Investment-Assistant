/**
 * Banking theme — Hebbia / Bloomberg-inspired dark professional style.
 * For B-1 信贷调查报告 / B-3 持仓预警 / 监控列表 entries.
 */

import { theme } from 'antd';
import type { ThemeConfig } from 'antd';
import { baseTokens } from './tokens-base';

export const bankingTokens = {
  // Color palette
  background: {
    primary: '#0a1929', // Deep navy
    secondary: '#132f4c',
    tertiary: '#1e3a5f',
  },
  text: {
    primary: '#e7ebf0',
    secondary: '#b2bac2',
    tertiary: '#788896',
  },
  border: {
    base: '#1e3a5f',
    strong: '#2d4f7c',
  },
  accent: {
    primary: '#d4af37', // Gold
    hover: '#e0c151',
  },
  // Numerical display: monospace for data density
  numFontFamily: baseTokens.fontFamily.mono,
} as const;

export const bankingThemeConfig: ThemeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: bankingTokens.accent.primary,
    colorBgContainer: bankingTokens.background.secondary,
    colorBgLayout: bankingTokens.background.primary,
    colorText: bankingTokens.text.primary,
    colorTextSecondary: bankingTokens.text.secondary,
    colorBorder: bankingTokens.border.base,
    fontFamily: baseTokens.fontFamily.sans,
    borderRadius: baseTokens.radius.sm,
  },
  components: {
    Table: {
      headerBg: bankingTokens.background.tertiary,
      borderColor: bankingTokens.border.base,
    },
    Card: {
      colorBgContainer: bankingTokens.background.secondary,
    },
  },
};
