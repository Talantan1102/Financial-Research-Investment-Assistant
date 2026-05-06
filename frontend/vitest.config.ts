/**
 * frontend/vitest.config.ts
 *
 * Vitest config for store/api unit tests. Independent from vite.config.ts so
 * Playwright + Vite dev server stay decoupled.
 *
 * - environment=jsdom: simulates window/document/localStorage in Node
 * - setupFiles: registers @testing-library/jest-dom matchers + reset state
 * - alias mirrors tsconfig "paths" so `@/...` resolves the same as in src
 * - css: false: skip CSS module transform — tests don't need styles
 */

import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      {
        find: /^@\//,
        replacement: fileURLToPath(new URL('./src/', import.meta.url)),
      },
    ],
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    css: false,
    // exclude playwright e2e dir from vitest discovery
    exclude: ['node_modules', 'dist', 'tests/e2e/**'],
  },
})
