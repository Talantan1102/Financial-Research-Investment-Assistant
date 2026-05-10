import { FileTextOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ChatMessage } from '@/types/chat'
import styles from '@/styles/chat.module.scss'

export interface ResearchReportCardProps {
  message: ChatMessage
  onContinueAsk?: (messageId: string) => void
}

export function ResearchReportCard({ message, onContinueAsk }: ResearchReportCardProps) {
  const [expanded, setExpanded] = useState(false)
  const navigate = useNavigate()
  const reportId = message.research_report_id
  const summary = message.research_report_summary ?? '(报告生成中)'
  return (
    <div className={styles.reportCard} data-report-id={reportId ?? undefined}>
      <div className={styles.reportCardHeader}>
        <FileTextOutlined />
        <strong>研报已生成</strong>
        <span className={styles.reportCardId}>#{reportId}</span>
      </div>
      <div className={styles.reportCardSummary}>{summary}</div>
      {expanded ? (
        <div className={styles.reportCardBody}>
          <p>完整报告请前往 Reports 页查看。</p>
        </div>
      ) : null}
      <div className={styles.reportCardActions}>
        <Button size="small" aria-label={expanded ? '收起' : '展开'} onClick={() => setExpanded((v) => !v)}>
          <span>{expanded ? '收起' : '展开'}</span>
        </Button>
        <Button
          size="small"
          type="primary"
          onClick={() => reportId && navigate(`/reports/${reportId}`)}
        >
          跳转 Reports
        </Button>
        <Button size="small" aria-label="继续提问" onClick={() => onContinueAsk?.(message.id)}>继续提问</Button>
      </div>
    </div>
  )
}
