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
import { useCallback, useEffect, useRef, useState } from 'react'
import { formatDecimalMoney } from './format-money'
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

function orderPrice(order: PaperOrder) {
  if (order.avg_fill_price) return formatDecimalMoney(order.avg_fill_price, 4)
  if (order.limit_price) return formatDecimalMoney(order.limit_price, 4)
  return '市价'
}

interface LoadState<T> {
  data: T | null
  error: string | null
  loading: boolean
}

const emptyLoadState = <T,>(): LoadState<T> => ({
  data: null,
  error: null,
  loading: false,
})

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof Error ? reason.message : fallback
}

export default function PaperTradingPage() {
  const [accountState, setAccountState] = useState<LoadState<PaperAccount>>(
    emptyLoadState,
  )
  const [holdingsState, setHoldingsState] =
    useState<LoadState<PaperHolding[]>>(emptyLoadState)
  const [ordersState, setOrdersState] =
    useState<LoadState<PaperOrder[]>>(emptyLoadState)
  const requestGeneration = useRef(0)

  const refresh = useCallback(() => {
    const generation = requestGeneration.current + 1
    requestGeneration.current = generation
    setAccountState((current) => ({
      ...current,
      error: null,
      loading: true,
    }))

    void (async () => {
      try {
        const loadedAccount = await getPaperAccount()
        if (requestGeneration.current !== generation) return
        setAccountState({ data: loadedAccount, error: null, loading: false })
        setHoldingsState((current) => ({
          ...current,
          error: null,
          loading: true,
        }))
        setOrdersState((current) => ({
          ...current,
          error: null,
          loading: true,
        }))

        void listPaperHoldings()
          .then((data) => {
            if (requestGeneration.current === generation) {
              setHoldingsState({ data, error: null, loading: false })
            }
          })
          .catch((reason) => {
            if (requestGeneration.current === generation) {
              setHoldingsState((current) => ({
                ...current,
                error: errorMessage(reason, '持仓读取失败'),
                loading: false,
              }))
            }
          })
        void listPaperOrders({
          account_generation: loadedAccount.generation,
          limit: 50,
        })
          .then((data) => {
            if (requestGeneration.current === generation) {
              setOrdersState({ data, error: null, loading: false })
            }
          })
          .catch((reason) => {
            if (requestGeneration.current === generation) {
              setOrdersState((current) => ({
                ...current,
                error: errorMessage(reason, '订单读取失败'),
                loading: false,
              }))
            }
          })
      } catch (reason) {
        if (requestGeneration.current === generation) {
          setAccountState((current) => ({
            ...current,
            error: errorMessage(reason, '模拟账户读取失败'),
            loading: false,
          }))
        }
      }
    })()
  }, [])

  useEffect(() => {
    refresh()
    return () => {
      requestGeneration.current += 1
    }
  }, [refresh])

  const account = accountState.data
  const holdings = holdingsState.data
  const orders = ordersState.data

  if (!account && accountState.loading) {
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
          <span>{accountState.error}</span>
          <span>持仓和订单尚未读取。</span>
          <button type="button" onClick={refresh}>
            重新读取
          </button>
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
        <div className={styles.headerActions}>
          <span className={styles.generation}>第 {account.generation} 轮</span>
          <button
            type="button"
            onClick={refresh}
            disabled={accountState.loading}
          >
            {accountState.loading ? '刷新中…' : '刷新账户'}
          </button>
        </div>
      </header>

      {accountState.error ? (
        <div className={styles.inlineError} role="alert">
          账户刷新失败：{accountState.error}
        </div>
      ) : null}

      <section className={styles.cashStrip} aria-label="资金概览">
        <div className={styles.primaryCash}>
          <span>可用资金</span>
          <strong>{formatDecimalMoney(account.available_cash)}</strong>
        </div>
        <div>
          <span>冻结资金</span>
          <strong>{formatDecimalMoney(account.frozen_cash)}</strong>
        </div>
        <div>
          <span>本轮初始资金</span>
          <strong>{formatDecimalMoney(account.initial_cash)}</strong>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeading}>
          <h2>当前持仓</h2>
          <span>{holdings ? `${holdings.length} 只` : '—'}</span>
        </div>
        {holdingsState.loading ? (
          <p className={styles.empty} aria-live="polite">
            正在读取持仓…
          </p>
        ) : holdingsState.error ? (
          <p className={styles.sectionError} role="alert">
            {holdingsState.error}
          </p>
        ) : holdings?.length === 0 ? (
          <p className={styles.empty}>还没有成交持仓。可以在对话里让 Agent 买入。</p>
        ) : holdings ? (
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
                    <td>{formatDecimalMoney(holding.average_cost, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeading}>
          <h2>最近订单</h2>
          <span>最多 50 笔</span>
        </div>
        {ordersState.loading ? (
          <p className={styles.empty} aria-live="polite">
            正在读取订单…
          </p>
        ) : ordersState.error ? (
          <p className={styles.sectionError} role="alert">
            {ordersState.error}
          </p>
        ) : orders?.length === 0 ? (
          <p className={styles.empty}>还没有订单。买卖指令会在确认后出现在这里。</p>
        ) : orders ? (
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
        ) : null}
      </section>
    </main>
  )
}
