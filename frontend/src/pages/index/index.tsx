import { AuditOutlined } from '@ant-design/icons'
import { Button, Input, message } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { reportActions } from '@/store/report'
import styles from './index.module.scss'

export default function Index() {
  const navigate = useNavigate()
  const [targetName, setTargetName] = useState('')
  const [tsCode, setTsCode] = useState('')
  const [starting, setStarting] = useState(false)

  const handleStartResearch = async () => {
    const name = targetName.trim()
    if (!name) {
      message.warning('请输入目标名称')
      return
    }
    setStarting(true)
    try {
      const id = await reportActions.startReport(name, tsCode.trim() || undefined)
      navigate(`/research/${id}`)
    } catch (err) {
      console.error('[Index] startReport failed:', err)
      message.error('启动研报失败,请稍后重试')
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className={styles['index-page']}>
      <header className={styles.hero}>
        <div className={styles['hero__brand']}>AlphaScout</div>
        <div className={styles['hero__tagline']}>Multi-agent Financial Research Platform</div>
        <div className={styles['hero__subtitle']}>
          通用金融 agent 平台 · 投资标的尽调首发场景
        </div>
      </header>

      <main className={styles['research-entry']}>
        <div className={styles['research-entry__header']}>
          <div className={styles['research-entry__icon']}>
            <AuditOutlined />
          </div>
          <div className={styles['research-entry__heading']}>
            <div className={styles['research-entry__title']}>新建投资尽调研报</div>
            <div className={styles['research-entry__desc']}>
              5-agent 协作产出完整尽调报告 — 覆盖基本面、估值、风险与投资建议
            </div>
          </div>
        </div>
        <div className={styles['research-entry__form']}>
          <Input
            placeholder="目标名称(如 贵州茅台)"
            value={targetName}
            onChange={(e) => setTargetName(e.target.value)}
            size="large"
            onPressEnter={handleStartResearch}
            disabled={starting}
          />
          <Input
            placeholder="股票代码(如 600519.SH,可选)"
            value={tsCode}
            onChange={(e) => setTsCode(e.target.value)}
            size="large"
            onPressEnter={handleStartResearch}
            disabled={starting}
          />
          <Button
            type="primary"
            size="large"
            onClick={handleStartResearch}
            loading={starting}
            disabled={!targetName.trim()}
            block
          >
            开始研究
          </Button>
        </div>
        <a className={styles['research-entry__history']} onClick={() => navigate('/research')}>
          查看历史研报 →
        </a>
      </main>
    </div>
  )
}
