/**
 * frontend/src/utils/report-to-markdown.ts
 *
 * Best-effort conversion of a `ReportDetail.report_json` payload to a
 * standalone Markdown string suitable for clipboard / file export.
 *
 * Why best-effort:
 *   The backend `writer_node` currently emits a markdown blob payload
 *   (`{ report_markdown, critic_scores, critic_overall }`), but the
 *   `InvestmentDueDiligenceReport` schema defines a section-keyed object.
 *   We support BOTH to be future-proof and avoid breakage when the
 *   backend swaps shape.
 *
 * Fallback chain:
 *   1. `report_markdown` field present → header + raw markdown blob
 *   2. Section-keyed object → header + per-section markdown render
 *   3. Otherwise → header + ```json``` stringify of the payload
 */

import type { InvestmentDueDiligenceReport } from '@/types/research'

const SECTION_TITLES: Record<string, string> = {
  target_overview: '一、标的概览',
  legal_qualification: '二、合规与资质',
  financial_analysis: '三、财务健康',
  industry_analysis: '四、行业地位',
  risk_assessment: '五、风险因素',
  investment_recommendation: '六、投资建议',
}

function sectionToMarkdown(data: unknown): string {
  if (data === null || data === undefined) return '_(此节无数据)_'
  if (typeof data === 'string') return data
  if (Array.isArray(data)) {
    return data
      .map((item, i) => {
        if (typeof item === 'object' && item !== null) {
          return `${i + 1}. \n\`\`\`json\n${JSON.stringify(item, null, 2)}\n\`\`\`\n`
        }
        return `${i + 1}. ${String(item)}`
      })
      .join('\n')
  }
  if (typeof data === 'object') {
    return Object.entries(data as Record<string, unknown>)
      .map(([k, v]) => {
        const valueStr =
          typeof v === 'object' && v !== null
            ? `\n\`\`\`json\n${JSON.stringify(v, null, 2)}\n\`\`\``
            : String(v)
        return `- **${k}**: ${valueStr}`
      })
      .join('\n')
  }
  return String(data)
}

export interface MetaInfo {
  target_name: string
  created_at: string
  cost: number
}

export function reportToMarkdown(
  report: InvestmentDueDiligenceReport | Record<string, unknown>,
  meta: MetaInfo,
): string {
  const r = report as Record<string, unknown>
  const header = `# ${meta.target_name} 投资尽调研报\n\n_生成于 ${meta.created_at}, 成本 ¥${meta.cost.toFixed(2)}_\n\n`

  // Fallback 1: backend markdown blob format (current writer_node output)
  if (typeof r.report_markdown === 'string' && r.report_markdown.length > 0) {
    return header + r.report_markdown
  }

  // Fallback 2: section-keyed schema (InvestmentDueDiligenceReport)
  const sections = Object.entries(SECTION_TITLES)
    .filter(([k]) => r[k] !== undefined && r[k] !== null)
    .map(([k, title]) => `## ${title}\n\n${sectionToMarkdown(r[k])}`)
    .join('\n\n---\n\n')

  if (sections) return header + sections

  // Fallback 3: nothing recognizable, dump JSON
  return `${header}\`\`\`json\n${JSON.stringify(r, null, 2)}\n\`\`\``
}
