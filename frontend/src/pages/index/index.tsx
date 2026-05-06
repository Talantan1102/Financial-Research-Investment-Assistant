import { AuditOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import ResearchEntry from '@/components/research-entry'
import styles from './index.module.scss'

const PIPELINE_STEPS = [
  { num: '01', name: 'Plan', desc: '拆解为 4 个维度的研究子任务' },
  { num: '02', name: 'Collect', desc: '5 个数据源并行 — 财务 / 行情 / 新闻 / 网页 / 知识库' },
  { num: '03', name: 'Analyze', desc: 'Analyst 提炼关键洞察与 thesis' },
  { num: '04', name: 'Draft', desc: 'Writer 产出 6 节结构化尽调报告' },
  { num: '05', name: 'Critique', desc: '6 维度 Critic 评分,综合 score' },
]

export default function Index() {
  const navigate = useNavigate()
  const today = new Date()
  const issueNo = `${today.getFullYear()} · ${String(today.getMonth() + 1).padStart(2, '0')}`

  return (
    <div className={styles['index-page']}>
      <div className={styles.shell}>
        {/* Top bar */}
        <div className={styles.topbar}>
          <span className={styles.topbar__brand}>AlphaScout</span>
          <span>
            <span className={styles.topbar__sep}>—</span> Research Issue {issueNo}{' '}
            <span className={styles.topbar__sep}>—</span> Powered by 5-agent collaboration
          </span>
        </div>

        {/* Hero */}
        <header className={styles.hero}>
          <div className={styles.hero__copy}>
            <div className={styles.hero__eyebrow}>Multi-agent · Investment Research</div>
            <h1 className={styles.hero__brand}>
              Alpha<span className={styles.italic}>Scout</span>.
            </h1>
            <p className={styles.hero__tagline}>
              A research desk where five agents argue, draft, and critique — until
              the report is fit to bring to your investment committee.
            </p>
            <div className={styles.hero__divider} />
            <p className={styles.hero__subtitle}>
              通用金融 agent 平台,首个落地场景为<strong>投资标的尽调</strong>。
              Planner / DataCollector / Analyst / Writer / Critic 五位 agent
              围绕你输入的标的协作 — 平均 3 分钟产出涵盖基本面、估值、风险与建议的结构化报告。
            </p>
          </div>

          <aside className={styles.hero__meta}>
            <div className={styles.hero__metaCard}>
              <div className={styles.hero__metaCard__label}>Latency</div>
              <div className={styles.hero__metaCard__value}>
                ≈ <span className="num">3</span> min
              </div>
              <div className={styles.hero__metaCard__hint}>
                平均 5-agent 流水线
              </div>
            </div>
            <div className={styles.hero__metaCard}>
              <div className={styles.hero__metaCard__label}>Cost</div>
              <div className={styles.hero__metaCard__value}>
                ¥ <span className="num">0.30</span>
              </div>
              <div className={styles.hero__metaCard__hint}>
                每份完整尽调研报
              </div>
            </div>
            <div className={styles.hero__metaCard}>
              <div className={styles.hero__metaCard__label}>Critic Dimensions</div>
              <div className={styles.hero__metaCard__value}>
                <span className="num">6</span>
              </div>
              <div className={styles.hero__metaCard__hint}>
                逻辑 / 数据 / 风险 / 合规 / 客户 / 可操作
              </div>
            </div>
          </aside>
        </header>

        {/* Research entry */}
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
                输入股票代码或名称,
                <span className={styles['research-entry__desc'] + ' pipeline'}>
                  <span className="pipeline">5-agent</span>
                </span>{' '}
                协作产出完整尽调 — 覆盖基本面、估值、风险与投资建议。
              </div>
            </div>
          </div>
          <ResearchEntry />
          <a
            className={styles['research-entry__history']}
            onClick={() => navigate('/research')}
          >
            View past reports <span className={styles.arrow}>→</span>
          </a>
        </main>

        {/* Pipeline visualization */}
        <section className={styles.pipeline}>
          <div className={styles.pipeline__label}>How AlphaScout works</div>
          <div className={styles.pipeline__row}>
            {PIPELINE_STEPS.map((s) => (
              <div key={s.num} className={styles.pipeline__step}>
                <div className={styles.pipeline__step__num}>{s.num}</div>
                <div className={styles.pipeline__step__name}>{s.name}</div>
                <div className={styles.pipeline__step__desc}>{s.desc}</div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
