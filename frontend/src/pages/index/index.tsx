import { AuditOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import ResearchEntry from '@/components/research-entry'
import styles from './index.module.scss'

export default function Index() {
  const navigate = useNavigate()

  return (
    <div className={styles['index-page']}>
      <header className={styles.hero}>
        <div className={styles['hero__brand']}>AlphaScout</div>
        <div className={styles['hero__tagline']}>
          Multi-agent Financial Research Platform
        </div>
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
            <div className={styles['research-entry__title']}>
              新建投资尽调研报
            </div>
            <div className={styles['research-entry__desc']}>
              5-agent 协作产出完整尽调报告 — 覆盖基本面、估值、风险与投资建议
            </div>
          </div>
        </div>
        <ResearchEntry />
        <a
          className={styles['research-entry__history']}
          onClick={() => navigate('/research')}
        >
          查看历史研报 →
        </a>
      </main>
    </div>
  )
}
