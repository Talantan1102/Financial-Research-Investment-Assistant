import {
  getPaperAccount,
  listPaperHoldings,
  listPaperOrders,
} from '@/api/paperTrading'
import type {
  PaperAccount,
  PaperHolding,
  PaperOrder,
  PaperOrderStatus,
} from '@/types/paper-trading'
import { useEffect, useState } from 'react'
import styles from './index.module.scss'

const statusLabels: Record<PaperOrderStatus, string> = {
  awaiting_confirmation: '待确认',
  queued: '排队中',
  open: '已报',
  partially_filled: '部分成交',
  filled: '已成交',
  cancelled: '已撤单',
  expired: '已过期',
  rejected: '已拒绝',
}

function money(value: string, digits = 2) {
  return `¥${Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`
}

function orderPrice(order: PaperOrder) {
  if (order.avg_fill_price) return money(order.avg_fill_price, 4)
  if (order.limit_price) return money(order.limit_price, 4)
  return '市价'
}

export default function PaperTradingPage() {
  const [account, setAccount] = useState<PaperAccount | null>(null)
  const [holdings, setHoldings] = useState<PaperHolding[]>([])
  const [orders, setOrders] = useState<PaperOrder[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    async function load() {
      try {
        const loadedAccount = await getPaperAccount()
        if (!active) return
        setAccount(loadedAccount)
        const [loadedHoldings, loadedOrders] = await Promise.all([
          listPaperHoldings(),
          listPaperOrders({ limit: 50 }),
        ])
        if (!active) return
        setHoldings(loadedHoldings)
        setOrders(loadedOrders)
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : '模拟账户读取失败')
        }
      }
    }
    void load()
    return () => {
      active = false
    }
  }, [])

  if (!account && !error) {
    return (
      <main className={styles.page}>
        <p className={styles.loading} aria-live="polite">
          正在读取模拟账户…
        </p>
      </main>
    )
  }

  if (!account) {
    return (
      <main className={styles.page}>
        <div className={styles.error} role="alert">
          <strong>模拟账户暂时无法打开</strong>
          <span>{error}</span>
        </div>
      </main>
    )
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>PAPER ACCOUNT</p>
          <h1>模拟账户</h1>
          <p>交易由 Agent 发起，这里只核对账户结果。</p>
        </div>
        <span className={styles.generation}>第 {account.generation} 轮</span>
      </header>

      {error ? (
        <div className={styles.inlineError} role="alert">
          {error}
        </div>
      ) : null}

      <section className={styles.cashStrip} aria-label="资金概览">
        <div className={styles.primaryCash}>
          <span>可用资金</span>
          <strong>{money(account.available_cash)}</strong>
        </div>
        <div>
          <span>冻结资金</span>
          <strong>{money(account.frozen_cash)}</strong>
        </div>
        <div>
          <span>本轮初始资金</span>
          <strong>{money(account.initial_cash)}</strong>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeading}>
          <h2>当前持仓</h2>
          <span>{holdings.length} 只</span>
        </div>
        {holdings.length === 0 ? (
          <p className={styles.empty}>还没有成交持仓。可以在对话里让 Agent 买入。</p>
        ) : (
          <div className={styles.tableWrap}>
            <table>
              <thead>
                <tr>
                  <th>股票</th>
                  <th>数量</th>
                  <th>可卖</th>
                  <th>冻结</th>
                  <th>平均成本</th>
                </tr>
              </thead>
              <tbody>
                {holdings.map((holding) => (
                  <tr key={holding.ts_code}>
                    <td>
                      <strong>{holding.name}</strong>
                      <small>{holding.ts_code}</small>
                    </td>
                    <td>{holding.quantity.toLocaleString('zh-CN')} 股</td>
                    <td>{holding.sellable_quantity.toLocaleString('zh-CN')} 股</td>
                    <td>{holding.frozen_quantity.toLocaleString('zh-CN')} 股</td>
                    <td>{money(holding.average_cost, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeading}>
          <h2>最近订单</h2>
          <span>最多 50 笔</span>
        </div>
        {orders.length === 0 ? (
          <p className={styles.empty}>还没有订单。买卖指令会在确认后出现在这里。</p>
        ) : (
          <div className={styles.tableWrap}>
            <table>
              <thead>
                <tr>
                  <th>股票</th>
                  <th>方向</th>
                  <th>数量</th>
                  <th>价格</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => (
                  <tr key={order.id}>
                    <td>
                      <strong>{order.name}</strong>
                      <small>{order.ts_code}</small>
                    </td>
                    <td>{order.side === 'buy' ? '买入' : '卖出'}</td>
                    <td>
                      {order.filled_quantity.toLocaleString('zh-CN')} /{' '}
                      {order.quantity.toLocaleString('zh-CN')}
                    </td>
                    <td>{orderPrice(order)}</td>
                    <td>
                      <span className={styles.status} data-status={order.status}>
                        {statusLabels[order.status]}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  )
}
