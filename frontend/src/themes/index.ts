/**
 * Theme provider hook + route-based theme selection.
 *
 * Banking entries (深色, B 端):
 *   /credit-report/* | /portfolio-monitoring/*
 *
 * Retail entries (浅色, C 端):
 *   /ticker/* | /watchlist/* | /screener/* | /monitoring/* | / (default)
 *
 * 注: /monitoring 原归 banking 深色,但与全站其他页(reports/portfolio/memory 等
 * 浅色 retail 风格)不一致,故改用 retail 浅色 theme 统一观感。banking 深色 theme
 * 暂无页面挂载,保留备未来 B 端独立入口用。
 */

import { useLocation } from 'react-router-dom';
import { bankingThemeConfig } from './tokens-banking';
import { retailThemeConfig } from './tokens-retail';

const BANKING_ROUTE_PREFIXES = [
  '/credit-report',
  '/portfolio-monitoring',
];

export function useActiveTheme() {
  const { pathname } = useLocation();
  const isBanking = BANKING_ROUTE_PREFIXES.some((p) => pathname.startsWith(p));
  return isBanking ? bankingThemeConfig : retailThemeConfig;
}

export { bankingThemeConfig, retailThemeConfig };
export { baseTokens } from './tokens-base';
export { bankingTokens } from './tokens-banking';
export { retailTokens } from './tokens-retail';
