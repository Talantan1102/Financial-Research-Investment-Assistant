/**
 * Theme provider hook + route-based theme selection.
 *
 * Banking entries (深色, B 端):
 *   /credit-report/* | /portfolio-monitoring/* | /monitoring/*
 *
 * Retail entries (浅色, C 端):
 *   /ticker/* | /watchlist/* | /screener/* | /chat/* | / (default)
 */

import { useLocation } from 'react-router-dom';
import { bankingThemeConfig } from './tokens-banking';
import { retailThemeConfig } from './tokens-retail';

const BANKING_ROUTE_PREFIXES = [
  '/credit-report',
  '/portfolio-monitoring',
  '/monitoring',
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
