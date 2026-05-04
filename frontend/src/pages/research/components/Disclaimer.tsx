/**
 * Disclaimer.tsx
 * Renders disclaimer banner (top or bottom) for D output report.
 * Uses antd Alert type="warning".
 */

import { Alert } from 'antd'
import type { InvestmentDueDiligenceReport } from '@/types/research'

interface DisclaimerProps {
  report: InvestmentDueDiligenceReport
  /** 'top' = compact alert banner, 'bottom' = footer full text */
  position?: 'top' | 'bottom'
  style?: React.CSSProperties
}

export default function Disclaimer({
  report,
  position = 'top',
  style,
}: DisclaimerProps) {
  if (position === 'top') {
    return (
      <Alert
        type="warning"
        showIcon
        banner={false}
        message="免责声明"
        description={report.disclaimer}
        style={{
          marginBottom: 20,
          borderRadius: 8,
          fontSize: 12,
          ...style,
        }}
      />
    )
  }

  // Bottom footer — full text, no icon
  return (
    <div
      style={{
        marginTop: 32,
        padding: '16px 20px',
        backgroundColor: '#fffbeb',
        border: '1px solid #f0d070',
        borderRadius: 8,
        fontSize: 12,
        color: '#5d6875',
        lineHeight: 1.7,
        ...style,
      }}
    >
      <strong style={{ color: '#1a1d21', display: 'block', marginBottom: 4 }}>
        免责声明
      </strong>
      {report.disclaimer}
    </div>
  )
}
