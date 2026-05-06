/**
 * frontend/src/components/export-button/index.tsx
 *
 * Export controls shown on the research detail page when the report is
 * `completed`. Two actions:
 *   - 复制 Markdown — `navigator.clipboard.writeText` of the rendered MD
 *   - 导出 PDF      — `window.print()` (browser native save-as-PDF flow);
 *                     `@media print` rules in index.css flatten the layout.
 *
 * No PDF library is bundled — keeping the artifact small and relying on
 * the browser print dialog is the v0.9.x decision.
 */

import { Button, message, Space } from 'antd'
import { CopyOutlined, FilePdfOutlined } from '@ant-design/icons'
import { reportToMarkdown } from '@/utils/report-to-markdown'
import type { ReportDetail } from '@/api/reports'
import type { InvestmentDueDiligenceReport } from '@/types/research'

interface Props {
  report: ReportDetail
}

export default function ExportButton({ report }: Props) {
  const handleCopyMarkdown = async () => {
    const md = reportToMarkdown(
      report.report_json as InvestmentDueDiligenceReport | Record<string, unknown>,
      {
        target_name: report.target_name,
        created_at: report.created_at,
        cost: report.cost,
      },
    )
    try {
      await navigator.clipboard.writeText(md)
      message.success('Markdown 已复制到剪贴板')
    } catch {
      message.error('复制失败,可能浏览器不支持 clipboard API')
    }
  }

  const handlePrintPDF = () => {
    message.info('请在浏览器对话框中选择"另存为 PDF"', 1.5)
    setTimeout(() => window.print(), 1200)
  }

  return (
    <Space>
      <Button icon={<CopyOutlined />} onClick={handleCopyMarkdown}>
        复制 Markdown
      </Button>
      <Button icon={<FilePdfOutlined />} onClick={handlePrintPDF}>
        导出 PDF
      </Button>
    </Space>
  )
}
