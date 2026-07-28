import { getMarketPermissions, type Market, type MarketEntitlement } from '@/api/investorSuitability'
import { Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import styles from './index.module.scss'

const markets: Array<{ market: Market; name: string; summary: string }> = [
  { market: 'main', name: '主板', summary: '普通股票交易市场，首次交易前需要完成风险揭示。' },
  { market: 'chinext', name: '创业板', summary: '需要 10 万元日均证券资产和 24 个月证券交易经验。' },
  { market: 'star', name: '科创板', summary: '需要 50 万元日均证券资产和 24 个月证券交易经验。' },
  { market: 'bse', name: '北交所', summary: '需要 50 万元日均证券资产和 24 个月证券交易经验。' },
]

const statusLabel: Record<string, string> = {
  not_applied: '尚未申请',
  pending_disclosure: '等待签署风险揭示书',
  enabled: '已开通',
  restricted: '受限制',
  revoked: '已撤销',
}

export default function MarketPermissionsPage() {
  const [permissions, setPermissions] = useState<MarketEntitlement[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void getMarketPermissions().then(setPermissions).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : '权限列表读取失败')
    })
  }, [])

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <p className={styles.eyebrow}>MARKET PERMISSIONS</p>
        <h1>市场交易权限</h1>
        <p>不同市场有不同准入条件。这里是独立申请流程，不会由对话 Agent 代替你提交或确认。</p>
      </header>
      {error ? <p className={styles.error} role="alert">{error}</p> : null}
      {!permissions && !error ? <p className={styles.loading}>正在读取权限状态…</p> : null}
      {permissions ? (
        <section className={styles.grid} aria-label="市场权限列表">
          {markets.map((item) => {
            const permission = permissions.find((entry) => entry.market === item.market)
            const enabled = permission?.status === 'enabled'
            return (
              <article className={styles.card} key={item.market}>
                <div className={styles.cardHeading}>
                  <h2>{item.name}</h2>
                  <span data-status={permission?.status ?? 'not_applied'}>
                    {statusLabel[permission?.status ?? 'not_applied']}
                  </span>
                </div>
                <p>{item.summary}</p>
                {enabled ? (
                  <p className={styles.enabled}>你已开通此市场权限，无需再次申请。</p>
                ) : (
                  <Link to={`/market-permissions/${item.market}/apply`}>查看条件并申请</Link>
                )}
              </article>
            )
          })}
        </section>
      ) : null}
    </main>
  )
}
