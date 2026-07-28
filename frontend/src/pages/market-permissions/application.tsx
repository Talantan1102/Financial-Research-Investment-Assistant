import {
  cancelApplication,
  confirmApplication,
  getMarketPermissions,
  startApplication,
  submitApplicationProfile,
  type FailedCondition,
  type Market,
  type MarketEntitlement,
} from '@/api/investorSuitability'
import { Link, useParams } from 'react-router-dom'
import { FormEvent, useEffect, useMemo, useState } from 'react'
import styles from './index.module.scss'

const marketDetails: Record<Market, { name: string; disclosureVersion: string; disclosure: string[] }> = {
  main: {
    name: '主板',
    disclosureVersion: 'main-risk-disclosure-2026-07',
    disclosure: ['主板股票价格可能上涨或下跌，历史表现不代表未来收益。', '请根据自身资金安排和风险承受能力独立作出交易决定。'],
  },
  chinext: {
    name: '创业板',
    disclosureVersion: 'chinext-risk-disclosure-2026-07',
    disclosure: ['创业板公司经营波动、估值变化和价格波动风险可能较高。', '你应理解准入条件不代表投资安全，并自行承担交易结果。'],
  },
  star: {
    name: '科创板',
    disclosureVersion: 'star-risk-disclosure-2026-07',
    disclosure: ['科创板企业可能具有较高的技术、经营和市场波动风险。', '股票价格可能大幅波动，存在亏损本金的可能。', '开通权限不构成任何收益承诺或投资建议，请独立判断后交易。'],
  },
  bse: {
    name: '北交所',
    disclosureVersion: 'bse-risk-disclosure-2026-07',
    disclosure: ['北交所股票流动性和价格波动可能与其他市场不同。', '你应充分理解市场规则、交易风险，并独立承担投资结果。'],
  },
}

type Step = 'loading' | 'profile' | 'disclosure' | 'rejected' | 'cancelled' | 'enabled'

function idempotencyKey(prefix: string) {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`
  return `${prefix}-${suffix}`
}

function formatValue(value: string | number) {
  return typeof value === 'number' ? value.toLocaleString('zh-CN') : Number(value).toLocaleString('zh-CN')
}

function failureText(failure: FailedCondition) {
  return failure.code === 'assets_below_minimum'
    ? '最近 20 个交易日日均证券资产未达到门槛'
    : '证券交易经验月数未达到门槛'
}

export interface PermissionApplicationPageProps {
  market?: Market
}

export default function PermissionApplicationPage({ market: marketProp }: PermissionApplicationPageProps) {
  const params = useParams<{ market: Market }>()
  const market = marketProp ?? params.market
  const details = market && market in marketDetails ? marketDetails[market] : null
  const [step, setStep] = useState<Step>('loading')
  const [entitlement, setEntitlement] = useState<MarketEntitlement | null>(null)
  const [applicationId, setApplicationId] = useState<string | null>(null)
  const [failures, setFailures] = useState<FailedCondition[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [disclosureRead, setDisclosureRead] = useState(false)
  const [profile, setProfile] = useState({ assets: '', months: '', riskLevel: 'C4' })

  const title = details?.name ?? '市场'
  const enabled = entitlement?.status === 'enabled'
  const disclosureVersion = useMemo(() => details?.disclosureVersion ?? '', [details])

  useEffect(() => {
    if (!details || !market) return
    void getMarketPermissions().then((items) => {
      const current = items.find((item) => item.market === market) ?? null
      setEntitlement(current)
      setStep(current?.status === 'enabled' ? 'enabled' : 'profile')
    }).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : '权限状态读取失败')
      setStep('profile')
    })
  }, [details, market])

  async function submitProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!market || !details) return
    setBusy(true)
    setError(null)
    try {
      const application = await startApplication(market, idempotencyKey('permission-start'))
      setApplicationId(application.application_id)
      const assessment = await submitApplicationProfile(application.application_id, {
        declared_average_assets_20d: profile.assets,
        securities_experience_months: Number(profile.months),
        risk_level: profile.riskLevel,
      })
      const rejected = assessment.failed_conditions ?? []
      setFailures(rejected)
      setStep(assessment.decision === 'passed' ? 'disclosure' : 'rejected')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '条件检查失败，请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  async function cancel() {
    if (!applicationId) return
    setBusy(true)
    setError(null)
    try {
      await cancelApplication(applicationId)
      setStep('cancelled')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '取消申请失败，请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  async function confirm() {
    if (!applicationId) return
    setBusy(true)
    setError(null)
    try {
      const result = await confirmApplication(applicationId, disclosureVersion, idempotencyKey('permission-confirm'))
      setEntitlement(result)
      setStep('enabled')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '开通失败，请刷新后重新确认')
    } finally {
      setBusy(false)
    }
  }

  if (!details) {
    return <main className={styles.page}><p className={styles.error} role="alert">不支持的市场权限类型。</p></main>
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <p className={styles.eyebrow}>MARKET PERMISSION APPLICATION</p>
        <h1>开通{title}交易权限</h1>
        <p>这是你主动发起的独立申请。系统会按当前规则检查你填写的资料；对话 Agent 不会替你申请或确认。</p>
      </header>
      {error ? <p className={styles.error} role="alert">{error}</p> : null}
      {step === 'loading' ? <p className={styles.loading}>正在读取你的权限状态…</p> : null}
      {step === 'enabled' || enabled ? (
        <section className={styles.panel}>
          <h2>{title}权限已开通</h2>
          <p>你可以继续使用该市场的买入、卖出和申购能力；无需再次申请。</p>
          <Link to="/market-permissions">返回市场权限列表</Link>
        </section>
      ) : null}
      {step === 'profile' ? (
        <form className={styles.panel} onSubmit={submitProfile}>
          <div className={styles.stepTitle}><span>第 1 步</span><h2>填写并检查准入资料</h2></div>
          <p className={styles.warning}><strong>请注意：</strong>以下数据由你自行填写，系统目前尚未核验。提交后会按规则判断是否满足开通条件。</p>
          <label>
            最近 20 个交易日日均证券资产
            <small>由你填写，单位为人民币元。它指最近 20 个交易日证券账户资产的平均值，不是账户余额。</small>
            <input aria-label="最近 20 个交易日日均证券资产" inputMode="decimal" min="0" required type="number" value={profile.assets} onChange={(event) => setProfile((current) => ({ ...current, assets: event.target.value }))} />
          </label>
          <label>
            证券交易经验月数
            <small>由你填写，从你开始证券交易到现在累计的月份数。</small>
            <input aria-label="证券交易经验月数" min="0" required type="number" value={profile.months} onChange={(event) => setProfile((current) => ({ ...current, months: event.target.value }))} />
          </label>
          <label>
            风险等级
            <small>由你填写的当前风险等级，仅用于留存本次申请资料快照。</small>
            <select aria-label="风险等级" value={profile.riskLevel} onChange={(event) => setProfile((current) => ({ ...current, riskLevel: event.target.value }))}>
              <option value="C1">C1</option><option value="C2">C2</option><option value="C3">C3</option><option value="C4">C4</option><option value="C5">C5</option>
            </select>
          </label>
          <button type="submit" disabled={busy}>{busy ? '检查中…' : '检查开通条件'}</button>
        </form>
      ) : null}
      {step === 'rejected' ? (
        <section className={styles.panel}>
          <div className={styles.stepTitle}><span>检查结果</span><h2>暂不满足开通条件</h2></div>
          <p>以下是系统根据你本次自行填写的资料得出的结果，未通过不会开通权限。</p>
          <ul className={styles.failures}>{failures.map((failure) => <li key={failure.code}><strong>{failureText(failure)}</strong><span>你的实际值：{formatValue(failure.actual)}；要求门槛：{formatValue(failure.required)}</span></li>)}</ul>
          <button type="button" className={styles.secondary} onClick={cancel} disabled={busy}>取消申请</button>
        </section>
      ) : null}
      {step === 'disclosure' ? (
        <section className={styles.panel}>
          <div className={styles.stepTitle}><span>第 2 步</span><h2>阅读风险揭示书并最终确认</h2></div>
          <p>你的资料已满足当前系统规则。开通前，请完整阅读以下风险揭示内容；确认后才会真正开通权限。</p>
          <article className={styles.disclosure} aria-label="风险揭示书">
            <h3>风险揭示书</h3>
            <p>版本：{disclosureVersion}</p>
            {details.disclosure.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
          </article>
          <label className={styles.checkbox}><input checked={disclosureRead} type="checkbox" onChange={(event) => setDisclosureRead(event.target.checked)} />我已完整阅读并理解以上风险揭示内容。</label>
          <div className={styles.actions}>
            <button type="button" className={styles.secondary} onClick={cancel} disabled={busy}>取消申请</button>
            <button type="button" onClick={confirm} disabled={busy || !disclosureRead}>{busy ? '提交中…' : '最终确认并开通'}</button>
          </div>
        </section>
      ) : null}
      {step === 'cancelled' ? <section className={styles.panel}><h2>申请已取消</h2><p>本次申请没有开通任何市场权限。需要时你可以重新发起申请。</p><Link to="/market-permissions">返回市场权限列表</Link></section> : null}
    </main>
  )
}
