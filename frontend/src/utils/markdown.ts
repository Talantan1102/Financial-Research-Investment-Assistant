import hljs from 'highlight.js'
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

export function renderMarkdown(content: string): string {
  return mdInstance.parse(content) as string
}
