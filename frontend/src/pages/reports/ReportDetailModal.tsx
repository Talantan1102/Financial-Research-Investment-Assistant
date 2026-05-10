import { Modal, Spin } from 'antd'
import { useEffect, useState } from 'react'
import { getReport, type ResearchReportDetail } from '@/api/reportsApi'
import { renderMarkdown } from '@/utils/markdown'

export default function ReportDetailModal({
  id,
  onClose,
}: {
  id: string
  onClose: () => void
}) {
  const [detail, setDetail] = useState<ResearchReportDetail | null>(null)
  useEffect(() => {
    let alive = true
    getReport(id)
      .then((d) => {
        if (alive) setDetail(d)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [id])
  return (
    <Modal open onCancel={onClose} footer={null} width={920} title={detail?.title ?? '加载中...'}>
      {!detail ? (
        <Spin />
      ) : (
        <div dangerouslySetInnerHTML={{ __html: renderMarkdown(detail.content_md) }} />
      )}
    </Modal>
  )
}
