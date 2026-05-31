/**
 * frontend/src/pages/reports/ReportDetailModal.tsx
 *
 * FIXED (bugs 2-4):
 *  - Was importing getReport from @/api/reportsApi (raw fetch, /api/v0/reports/{id},
 *    wrong schema with content_md/title that don't exist in backend).
 *  - Now uses @/api/reports (axios request, /reports/{id}, correct ReportDetail schema).
 *  - title uses detail.target_name (actual backend field).
 *  - body renders via reportToMarkdown(report_json) — defensive 3-fallback chain.
 *  - Fail-loud: .catch(() => {}) replaced with error state + visible message.
 */
import { Alert, Modal, Spin } from 'antd'
import { useEffect, useState } from 'react'
import { marked } from 'marked'
import { getReport, type ReportDetail } from '@/api/reports'
import { reportToMarkdown } from '@/utils/report-to-markdown'

export default function ReportDetailModal({
  id,
  onClose,
}: {
  id: string
  onClose: () => void
}) {
  const [detail, setDetail] = useState<ReportDetail | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setDetail(null)
    setLoadError(null)
    getReport(id)
      .then((res) => {
        if (alive) setDetail(res.data)
      })
      .catch((err: unknown) => {
        if (!alive) return
        const msg = err instanceof Error ? err.message : String(err)
        setLoadError(msg)
      })
    return () => {
      alive = false
    }
  }, [id])

  const title = detail?.target_name ?? '加载中...'

  const bodyContent = () => {
    if (loadError) {
      return (
        <Alert
          type="error"
          message="加载研报详情失败"
          description={loadError}
          showIcon
        />
      )
    }
    if (!detail) return <Spin />
    const md = reportToMarkdown(detail.report_json, {
      target_name: detail.target_name,
      created_at: (detail.created_at as unknown) instanceof Date
        ? (detail.created_at as unknown as Date).toISOString()
        : String(detail.created_at),
      cost: detail.cost,
    })
    return (
      <div
        dangerouslySetInnerHTML={{ __html: marked.parse(md) as string }}
      />
    )
  }

  return (
    <Modal
      open
      onCancel={onClose}
      footer={null}
      width={920}
      title={title}
    >
      {bodyContent()}
    </Modal>
  )
}
