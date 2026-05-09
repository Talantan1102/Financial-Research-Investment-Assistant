import { Button, Modal, Spin, Tabs } from 'antd'
import { useSnapshot } from 'valtio'
import { escalationState } from '@/store/escalation'
import { ChatDerivedSignalsForm } from './ChatDerivedSignalsForm'
import { ExplicitTaskForm } from './ExplicitTaskForm'
import { KnownFactsForm } from './KnownFactsForm'
import { MissingFieldBanner } from './MissingFieldBanner'
import { SessionMetadataForm } from './SessionMetadataForm'
import styles from '@/styles/escalation.module.scss'

export function EscalationConfirmDialog() {
  const snap = useSnapshot(escalationState)
  if (!snap.dialog_open) return null
  const draft = snap.packet_draft

  return (
    <Modal
      open={snap.dialog_open}
      title="升级到深度研究 — 确认 Escalation Packet"
      onCancel={() => {
        escalationState.dialog_open = false
      }}
      width={960}
      footer={null}
      className={styles.escalationDialog}
    >
      {!draft ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin tip="正在分析对话生成升级摘要..." />
        </div>
      ) : (
        <>
          <MissingFieldBanner hints={[...draft.missing_field_hints]} />
          <Tabs
            defaultActiveKey="explicit"
            items={[
              {
                key: 'explicit',
                label: '明确任务 / Explicit Task',
                forceRender: true,
                children: <ExplicitTaskForm value={draft.explicit_task} />,
              },
              {
                key: 'signals',
                label: '对话信号 / Chat Derived Signals',
                forceRender: true,
                children: <ChatDerivedSignalsForm value={draft.chat_derived_signals} />,
              },
              {
                key: 'facts',
                label: '已知事实 / Known Facts',
                forceRender: true,
                children: <KnownFactsForm value={draft.known_facts} />,
              },
              {
                key: 'meta',
                label: 'Session 元数据 / Session Metadata',
                forceRender: true,
                children: <SessionMetadataForm value={draft.session_metadata} />,
              },
            ]}
          />
          <div className={styles.dialogFooter}>
            <Button
              onClick={() => {
                escalationState.dialog_open = false
              }}
            >
              取消
            </Button>
            <Button
              type="primary"
              data-testid="escalation-confirm-btn"
              onClick={() => {
                /* wired in Task 22 */
              }}
            >
              确认并启动深度研究
            </Button>
          </div>
        </>
      )}
    </Modal>
  )
}
