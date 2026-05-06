/**
 * frontend/src/components/report-canvas/index.tsx
 *
 * D output report canvas (PDF-like long scroll + sticky Anchor mini ToC).
 * Renders the 6-section InvestmentDueDiligenceReport produced by v0.9.x backend.
 *
 * 简化版 renderSectionData:把 section payload (string / array / object) 转成
 * markdown,后续 Task 13.x 可以按字段语义渲染表格。
 */

import { Anchor, Typography } from 'antd'
import { marked } from 'marked'
import type { InvestmentDueDiligenceReport } from '@/types/research'
import styles from './index.module.scss'

interface Props {
  report: InvestmentDueDiligenceReport | Record<string, unknown>
}

interface SectionDef {
  key: string
  title: string
  data: unknown
}

// 章节顺序与中文标题(与 backend schema sections 对应)
const SECTION_ORDER: { key: string; title: string }[] = [
  { key: 'target_overview', title: '一、标的概览' },
  { key: 'legal_qualification', title: '二、合规与资质' },
  { key: 'financial_health', title: '三、财务健康' },
  { key: 'industry_position', title: '四、行业地位' },
  { key: 'risk_factors', title: '五、风险因素' },
  { key: 'investment_recommendation', title: '六、投资建议' },
]

function renderSectionData(data: unknown): string {
  /** 把 section data 转 markdown.
   * 简化版:object → key-value list;array → numbered list;后续可按字段语义优化。
   */
  if (data === null || data === undefined) return '_(此节无数据)_'
  if (typeof data === 'string') return data
  if (Array.isArray(data)) {
    return data
      .map((item, i) => {
        const itemStr =
          typeof item === 'object' && item !== null
            ? '\n```json\n' + JSON.stringify(item, null, 2) + '\n```'
            : String(item)
        return `${i + 1}. ${itemStr}`
      })
      .join('\n')
  }
  if (typeof data === 'object') {
    return Object.entries(data as Record<string, unknown>)
      .map(([k, v]) => {
        const valueStr =
          typeof v === 'object' && v !== null
            ? '\n```json\n' + JSON.stringify(v, null, 2) + '\n```'
            : String(v)
        return `- **${k}**: ${valueStr}`
      })
      .join('\n')
  }
  return String(data)
}

export default function ReportCanvas({ report }: Props) {
  const sections: SectionDef[] = SECTION_ORDER.filter((s) => {
    const v = (report as Record<string, unknown>)[s.key]
    return v !== undefined && v !== null
  }).map((s) => ({
    ...s,
    data: (report as Record<string, unknown>)[s.key],
  }))

  if (sections.length === 0) {
    return (
      <Typography.Paragraph type="secondary">
        研报内容生成中或为空。
      </Typography.Paragraph>
    )
  }

  return (
    <div className={styles.container}>
      <div className={styles.canvas}>
        {sections.map((s) => (
          <section key={s.key} id={s.key} className={styles.section}>
            <Typography.Title level={2}>{s.title}</Typography.Title>
            <div
              className={styles.markdown}
              dangerouslySetInnerHTML={{
                __html: marked.parse(renderSectionData(s.data)) as string,
              }}
            />
          </section>
        ))}
      </div>
      <aside className={styles.toc}>
        <Anchor
          items={sections.map((s) => ({
            key: s.key,
            href: `#${s.key}`,
            title: s.title,
          }))}
          targetOffset={80}
        />
      </aside>
    </div>
  )
}
