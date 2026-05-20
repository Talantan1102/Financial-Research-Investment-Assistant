import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ChatMessage } from '@/types/chat'
import { Icon } from '@/components/shared/Icon'
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
      <div className={styles.reportCardHead}>
        <div className={styles.reportCardIconLarge}>
          <Icon name="document" size={18} aria-hidden />
        </div>
        <div className={styles.reportCardHeadText}>
          <div className={styles.reportCardId}>#{reportId}</div>
          <div className={styles.reportCardTitle}>{message.content || '研报已生成'}</div>
        </div>
      </div>
      <div className={styles.reportCardSummary}>{summary}</div>
      {expanded ? (
        <div className={styles.reportCardBody}>
          <p>完整报告请前往 Reports 页查看。</p>
        </div>
      ) : null}
      <div className={styles.reportCardActions}>
        <button
          type="button"
          className={styles.pillBtn}
          aria-label={expanded ? '收起' : '展开'}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? '收起' : '展开'}
        </button>
        <button
          type="button"
          className={`${styles.pillBtn} ${styles.primary}`}
          onClick={() => reportId && navigate(`/reports/${reportId}`)}
        >
          跳转 Reports
        </button>
        <button
          type="button"
          className={styles.pillBtn}
          onClick={() => onContinueAsk?.(message.id)}
        >
          继续提问
        </button>
      </div>
    </div>
  )
}
