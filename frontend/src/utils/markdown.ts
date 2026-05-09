import hljs from 'highlight.js'
import katex from 'katex'
import { Marked } from 'marked'

/**
 * Marked instance with highlight.js.
 * Uses postprocess hook to strip <script> tags (XSS prevention).
 * Code-fence walkTokens stashes highlighted HTML; renderer.code returns it.
 */
export const mdInstance = new Marked({
  gfm: true,
  breaks: true,
})

// Strip dangerous HTML tags via postprocess hook (marked v15)
mdInstance.use({
  hooks: {
    postprocess(html: string): string {
      return html.replace(/<script[\s\S]*?<\/script>/gi, '')
    },
  },
})

mdInstance.use({
  walkTokens(token) {
    if (token.type === 'code') {
      const code = token as { type: 'code'; lang?: string; text: string }
      const lang = code.lang && hljs.getLanguage(code.lang) ? code.lang : 'plaintext'
      const highlighted = hljs.highlight(code.text, {
        language: lang,
        ignoreIllegals: true,
      }).value
      ;(code as unknown as { _hljs?: string; _lang?: string })._hljs =
        `<pre><code class="hljs language-${lang}">${highlighted}</code></pre>`
    }
  },
  renderer: {
    code(token) {
      const t = token as { _hljs?: string }
      if (t._hljs) return t._hljs
      return false
    },
  },
})

const BLOCK_MATH = /\$\$([\s\S]+?)\$\$/g
const INLINE_MATH = /\$([^\n$]+?)\$/g

function renderKatex(html: string): string {
  let out = html.replace(BLOCK_MATH, (full, expr: string) => {
    try {
      return katex.renderToString(expr, { displayMode: true, throwOnError: false })
    } catch {
      return full
    }
  })
  out = out.replace(INLINE_MATH, (full, expr: string) => {
    try {
      return katex.renderToString(expr, { displayMode: false, throwOnError: false })
    } catch {
      return full
    }
  })
  return out
}

export function renderMarkdown(content: string): string {
  const raw = mdInstance.parse(content) as string
  return renderKatex(raw)
}

import type { ChartSpec } from '@/types/chat'

const CHART_FENCE = /```chart_spec\n([\s\S]+?)\n```/g

function extractCharts(content: string): {
  stripped: string
  charts: Array<{ id: string; spec: ChartSpec }>
} {
  const charts: Array<{ id: string; spec: ChartSpec }> = []
  let i = 0
  const stripped = content.replace(CHART_FENCE, (_, json: string) => {
    try {
      const spec = JSON.parse(json) as ChartSpec
      const id = `chart-${i++}`
      charts.push({ id, spec })
      return `<div data-chart-spec-id="${id}"></div>`
    } catch {
      return '`(chart_spec parse error)`'
    }
  })
  return { stripped, charts }
}

export interface MarkdownRenderResult {
  html: string
  charts: Array<{ id: string; spec: ChartSpec }>
}

export function renderMarkdownWithCharts(content: string): MarkdownRenderResult {
  const { stripped, charts } = extractCharts(content)
  const raw = mdInstance.parse(stripped) as string
  const html = renderKatex(raw)
  return { html, charts }
}
