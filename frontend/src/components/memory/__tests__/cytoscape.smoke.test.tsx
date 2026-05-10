/**
 * Smoke test for cytoscape + react-cytoscapejs deps (Plan 7B Task 1).
 *
 * Verifies:
 * - cytoscape import resolves (function constructor)
 * - react-cytoscapejs exports default React component
 *
 * Note: jsdom lacks real <canvas>; CytoscapeComponent mount triggers
 * cytoscape's textureOnViewport renderer which expects 2D context. Live
 * graph layout 验证 deferred to Playwright e2e (Task 8). The smoke test
 * here only proves the deps are importable + component is a valid type.
 */
import cytoscape from 'cytoscape'
import CytoscapeComponent from 'react-cytoscapejs'
import { describe, expect, it } from 'vitest'

describe('cytoscape smoke', () => {
  it('imports cytoscape as a function', () => {
    expect(cytoscape).toBeDefined()
    expect(typeof cytoscape).toBe('function')
  })

  it('exports react-cytoscapejs default as a React component constructor', () => {
    expect(CytoscapeComponent).toBeDefined()
    // Class component: constructor + prototype.render
    expect(typeof CytoscapeComponent).toBe('function')
  })
})
