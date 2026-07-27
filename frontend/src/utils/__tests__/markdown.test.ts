/**
 * frontend/src/utils/__tests__/markdown.test.ts
 *
 * C31: Regression tests for renderMarkdown XSS prevention.
 * Verifies that <script> tags in LLM-generated content are stripped by the
 * hardened renderMarkdown() from utils/markdown.ts (which uses a private
 * Marked instance with a postprocess hook).
 */
import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '@/utils/markdown'

describe('renderMarkdown — C31 XSS prevention', () => {
  it('strips inline <script> tags from rendered output', () => {
    const input = 'Hello <script>window.__xss=1</script> World'
    const html = renderMarkdown(input)
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('window.__xss')
    expect(html).toContain('Hello')
    expect(html).toContain('World')
  })

  it('strips multi-line <script>...</script> blocks', () => {
    const input = `## Title\n\n<script>\nvar x = "evil";\ndocument.body.innerHTML = x;\n</script>\n\nSafe content`
    const html = renderMarkdown(input)
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('document.body.innerHTML')
    expect(html).toContain('Safe content')
  })

  it('strips <SCRIPT> (case-insensitive)', () => {
    const input = '<SCRIPT>alert("xss")</SCRIPT>'
    const html = renderMarkdown(input)
    expect(html).not.toContain('<SCRIPT>')
    expect(html).not.toContain('alert')
  })

  it('renders normal markdown (bold, headers, links) correctly', () => {
    const input = '# Header\n\n**bold text** and [link](https://example.com)'
    const html = renderMarkdown(input)
    expect(html).toContain('<h1')
    expect(html).toContain('<strong>')
    expect(html).toContain('bold text')
    expect(html).toContain('href="https://example.com"')
  })

  it('handles empty string without throwing', () => {
    expect(() => renderMarkdown('')).not.toThrow()
  })

  it('handles markdown with code fences without stripping them', () => {
    const input = '```js\nconsole.log("hello")\n```'
    const html = renderMarkdown(input)
    // Code fences should not be stripped — only <script> tags are blocked
    const document = new DOMParser().parseFromString(html, 'text/html')
    expect(document.querySelector('code')?.textContent).toContain(
      'console.log',
    )
  })
})
