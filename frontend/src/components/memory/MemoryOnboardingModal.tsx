/**
 * MemoryOnboardingModal (Plan 7B Task 5) — 首次 session 强 onboarding 弹窗.
 *
 * #8 算法深度补丁 (b): spec § 11 "上线第一周用户问'你怎么监视我'".
 * 800ms 微延迟避免跟登录 modal 撞重叠.
 *
 * localStorage `memory_onboarding_seen_v1` 标记不重复弹.
 *
 * 注意: 仅登录态用户路径下挂载, 路由层 AuthGuard 已守护; logout 状态用户
 * 看不到此 modal.
 */
import { Button, List, Modal, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

const { Paragraph, Text } = Typography

const STORAGE_KEY = 'memory_onboarding_seen_v1'

export function hasSeenOnboarding(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

export function markOnboardingSeen(): void {
  try {
    localStorage.setItem(STORAGE_KEY, '1')
  } catch {
    // localStorage disabled (private window etc.) — accept re-prompt next visit
  }
}

const RECORDED_ITEMS = [
  '您的持仓 / 加减仓变动',
  '您对某只股 / 某行业的偏好与回避',
  '您表达的观点 (看好 / 看空 / 中性)',
  '您研究过的标的与对比',
]

const CONTROL_ITEMS = [
  '在 /memory 页查看所有记录 (graph / timeline / audit 三视图)',
  '对任何 fact 一键否决 (立即生效, 不再影响 retrieval)',
  '看到我引用 memory 时, 我会在回复中显式提示 [查看] 链接',
]

export default function MemoryOnboardingModal() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    if (!hasSeenOnboarding()) {
      const t = setTimeout(() => setOpen(true), 800)
      return () => clearTimeout(t)
    }
    return undefined
  }, [])

  const close = () => {
    markOnboardingSeen()
    setOpen(false)
  }

  const goMemory = () => {
    markOnboardingSeen()
    setOpen(false)
    navigate('/memory')
  }

  return (
    <Modal
      open={open}
      onCancel={close}
      maskClosable={false}
      title="一件事:我会记住您的投资偏好和持仓"
      width={560}
      data-testid="memory-onboarding-modal"
      footer={[
        <Button
          key="memory"
          type="default"
          onClick={goMemory}
          data-testid="onboarding-go-memory"
        >
          去 /memory 看看
        </Button>,
        <Button
          key="ok"
          type="primary"
          onClick={close}
          data-testid="onboarding-confirm"
        >
          我知道了
        </Button>,
      ]}
    >
      <Paragraph>
        为了给您更贴合的研究建议, 我会从您的对话中{' '}
        <Text strong>自动</Text>记录:
      </Paragraph>
      <List
        size="small"
        bordered
        dataSource={RECORDED_ITEMS}
        renderItem={(item) => <List.Item>{item}</List.Item>}
      />
      <Paragraph style={{ marginTop: 16 }}>
        这些信息<Text strong>仅用于本会话</Text>, 不会跨用户共享。
      </Paragraph>
      <Paragraph>
        <Text strong>您随时可以:</Text>
      </Paragraph>
      <List
        size="small"
        dataSource={CONTROL_ITEMS}
        renderItem={(item) => <List.Item>{item}</List.Item>}
      />
    </Modal>
  )
}
