/**
 * ResearchEntry — 投资尽调启动 form,landing hero + /research Modal 共用。
 *
 * Props:
 *  - onSuccess?: (id) => void — 提交成功回调,默认跳 /research/:id
 *  - className?: 额外 wrapper class
 */

import { Button, Input, message } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { reportActions } from '@/store/report'

interface Props {
  onSuccess?: (id: string) => void
  className?: string
}

export default function ResearchEntry({ onSuccess, className }: Props) {
  const navigate = useNavigate()
  const [targetName, setTargetName] = useState('')
  const [tsCode, setTsCode] = useState('')
  const [starting, setStarting] = useState(false)

  const handleStart = async () => {
    const name = targetName.trim()
    if (!name) {
      message.warning('请输入目标名称')
      return
    }
    setStarting(true)
    try {
      const id = await reportActions.startReport(
        name,
        tsCode.trim() || undefined,
      )
      if (onSuccess) {
        onSuccess(id)
      } else {
        navigate(`/research/${id}`)
      }
    } catch (err) {
      console.error('[ResearchEntry] startReport failed:', err)
      message.error('启动研报失败,请稍后重试')
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className={className}>
      <Input
        placeholder="目标名称(如 贵州茅台)"
        value={targetName}
        onChange={(e) => setTargetName(e.target.value)}
        size="large"
        onPressEnter={handleStart}
        disabled={starting}
        style={{ marginBottom: 12 }}
      />
      <Input
        placeholder="股票代码(如 600519.SH,可选)"
        value={tsCode}
        onChange={(e) => setTsCode(e.target.value)}
        size="large"
        onPressEnter={handleStart}
        disabled={starting}
        style={{ marginBottom: 16 }}
      />
      <Button
        type="primary"
        size="large"
        block
        onClick={handleStart}
        loading={starting}
        disabled={!targetName.trim()}
      >
        开始研究
      </Button>
    </div>
  )
}
