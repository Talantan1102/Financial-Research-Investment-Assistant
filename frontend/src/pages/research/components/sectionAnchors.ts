/**
 * sectionAnchors.ts
 * Shared section anchor definitions for D output report outline and sections.
 * Separated from ReportOutline.tsx to satisfy react-refresh/only-export-components.
 */

export const SECTION_ANCHORS = [
  { id: 'section-overview', label: '§ 1 公司概况' },
  { id: 'section-legal', label: '§ 2 法律资质' },
  { id: 'section-financial', label: '§ 3 财务分析' },
  { id: 'section-industry', label: '§ 4 行业分析' },
  { id: 'section-risk', label: '§ 5 风险评估' },
  { id: 'section-recommendation', label: '§ 6 投资建议' },
] as const
