/**
 * ErrorBanner.tsx
 * Renders different banners / modals based on ErrorState.type.
 *
 * Types:
 *   degraded_mode   → warning Alert showing which tool degraded
 *   schema_fallback → warning Alert "结构化降级至 markdown"
 *   cost_exceeded   → error Modal "已触达每日 ¥20 上限"
 *   sse_disconnected → error Alert with refresh action
 *   agent_crash      → error Alert with log ID + retry button
 */

import { Alert, Button, Modal } from 'antd'
import {
  ExclamationCircleOutlined,
  ReloadOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import type { ErrorState } from '@/types/research'

interface ErrorBannerProps {
  error: ErrorState
  onRetry?: () => void
  /** Dismiss / clear the error */
  onDismiss?: () => void
  style?: React.CSSProperties
}

export default function ErrorBanner({
  error,
  onRetry,
  onDismiss,
  style,
}: ErrorBannerProps) {
  switch (error.type) {
    // ── Degraded mode ────────────────────────────────────────────────────────
    case 'degraded_mode':
      return (
        <Alert
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          message="工具降级"
          description={
            error.degradedTool
              ? `「${error.degradedTool}」工具不可用，已切换至降级模式。部分数据可能不完整，报告生成仍继续。`
              : `部分工具不可用，已切换至降级模式。${error.message}`
          }
          closable={!!onDismiss}
          onClose={onDismiss}
          style={{ borderRadius: 8, ...style }}
        />
      )

    // ── Schema fallback ──────────────────────────────────────────────────────
    case 'schema_fallback':
      return (
        <Alert
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          message="结构化降级"
          description="报告结构化输出失败，已降级为 Markdown 格式。部分章节可能显示不完整。"
          closable={!!onDismiss}
          onClose={onDismiss}
          style={{ borderRadius: 8, ...style }}
        />
      )

    // ── Cost exceeded ────────────────────────────────────────────────────────
    case 'cost_exceeded':
      return (
        <Modal
          open
          closable={!!onDismiss}
          onCancel={onDismiss}
          title={
            <span style={{ color: '#c0392b' }}>
              <ExclamationCircleOutlined style={{ marginRight: 8 }} />
              每日费用上限
            </span>
          }
          footer={[
            <Button key="dismiss" onClick={onDismiss}>
              知道了
            </Button>,
          ]}
          centered
        >
          <p style={{ fontSize: 14, color: '#1a1d21' }}>
            今日 AI 调用费用已触达每日 ¥20 上限，本次请求已中止。
          </p>
          <p style={{ fontSize: 13, color: '#8a96a3', marginTop: 4 }}>
            {error.message}
          </p>
        </Modal>
      )

    // ── SSE disconnected ─────────────────────────────────────────────────────
    case 'sse_disconnected':
      return (
        <Alert
          type="error"
          showIcon
          message="连接断开"
          description="与服务器的连接意外中断，请刷新页面重试。"
          closable={!!onDismiss}
          onClose={onDismiss}
          action={
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => window.location.reload()}
            >
              刷新
            </Button>
          }
          style={{ borderRadius: 8, ...style }}
        />
      )

    // ── Agent crash ──────────────────────────────────────────────────────────
    case 'agent_crash':
      return (
        <Alert
          type="error"
          showIcon
          message="尽调生成失败"
          description={
            <div>
              <div>{error.message}</div>
              {error.requestId && (
                <div style={{ fontSize: 11, color: '#8a96a3', marginTop: 4, fontFamily: 'monospace' }}>
                  log id: {error.requestId}
                </div>
              )}
            </div>
          }
          closable={!!onDismiss}
          onClose={onDismiss}
          action={
            onRetry ? (
              <Button
                size="small"
                danger
                icon={<ReloadOutlined />}
                onClick={onRetry}
              >
                重试
              </Button>
            ) : undefined
          }
          style={{ borderRadius: 8, ...style }}
        />
      )

    default:
      return (
        <Alert
          type="error"
          showIcon
          message="未知错误"
          description={error.message}
          closable={!!onDismiss}
          onClose={onDismiss}
          style={{ borderRadius: 8, ...style }}
        />
      )
  }
}
