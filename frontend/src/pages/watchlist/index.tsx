import {
  addWatchlistItem,
  listWatchlist,
  removeWatchlistItem,
  updateWatchlistItem,
  type WatchlistItem,
} from '@/api/watchlist'
import { useEffect, useRef, useState } from 'react'
import styles from './index.module.scss'

const TS_CODE = /^\d{6}\.(SH|SZ)$/

export default function WatchlistPage() {
  const [items, setItems] = useState<WatchlistItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [adding, setAdding] = useState(false)
  const [editingCode, setEditingCode] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [monitoring, setMonitoring] = useState(false)
  const [savingCode, setSavingCode] = useState<string | null>(null)
  const mutationVersion = useRef(0)

  useEffect(() => {
    const requestedAt = mutationVersion.current
    let active = true
    listWatchlist()
      .then((rows) => {
        if (active && mutationVersion.current === requestedAt) setItems(rows)
      })
      .catch((reason) => {
        if (active) {
          setError(reason instanceof Error ? reason.message : '自选股读取失败')
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  async function addItem() {
    const normalizedCode = code.trim().toUpperCase()
    const normalizedName = name.trim()
    if (!TS_CODE.test(normalizedCode)) {
      setError('股票代码格式应为 6 位数字加 .SH 或 .SZ')
      return
    }
    if (!normalizedName) {
      setError('请填写股票名称')
      return
    }
    if (adding) return
    setAdding(true)
    setError(null)
    mutationVersion.current += 1
    try {
      const added = await addWatchlistItem({
        ts_code: normalizedCode,
        name: normalizedName,
        monitoring_enabled: false,
      })
      setItems((current) => {
        const withoutDuplicate = current.filter(
          (item) => item.ts_code !== added.ts_code,
        )
        return [...withoutDuplicate, added]
      })
      setCode('')
      setName('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '加入自选失败')
    } finally {
      setAdding(false)
    }
  }

  function beginEdit(item: WatchlistItem) {
    setEditingCode(item.ts_code)
    setNote(item.note ?? '')
    setMonitoring(item.monitoring_enabled)
  }

  async function saveItem(item: WatchlistItem) {
    if (savingCode) return
    setSavingCode(item.ts_code)
    setError(null)
    mutationVersion.current += 1
    try {
      const saved = await updateWatchlistItem(item.ts_code, {
        note: note.trim() || null,
        monitoring_enabled: monitoring,
      })
      setItems((current) =>
        current.map((row) => (row.ts_code === saved.ts_code ? saved : row)),
      )
      setEditingCode(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存自选股失败')
    } finally {
      setSavingCode(null)
    }
  }

  async function removeItem(item: WatchlistItem) {
    if (savingCode) return
    setSavingCode(item.ts_code)
    setError(null)
    mutationVersion.current += 1
    try {
      await removeWatchlistItem(item.ts_code)
      setItems((current) =>
        current.filter((row) => row.ts_code !== item.ts_code),
      )
      if (editingCode === item.ts_code) setEditingCode(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '移除自选股失败')
    } finally {
      setSavingCode(null)
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p>WATCHLIST</p>
          <h1>自选股</h1>
          <span>改动会直接保存；开启监控后才会进入定时检查。</span>
        </div>
        <span className={styles.count}>{items.length} 只</span>
      </header>

      <section className={styles.addPanel} aria-label="新增自选股">
        <label>
          <span>股票代码</span>
          <input
            value={code}
            onChange={(event) => setCode(event.target.value)}
            placeholder="600519.SH"
            autoComplete="off"
          />
        </label>
        <label>
          <span>股票名称</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="贵州茅台"
            autoComplete="off"
          />
        </label>
        <button type="button" onClick={() => void addItem()} disabled={adding}>
          {adding ? '正在加入…' : '加入自选'}
        </button>
      </section>

      {error ? (
        <div className={styles.error} role="alert">
          {error}
        </div>
      ) : null}

      {loading && items.length === 0 ? (
        <p className={styles.empty} aria-live="polite">
          正在读取自选股…
        </p>
      ) : items.length === 0 ? (
        <p className={styles.empty}>还没有自选股。输入代码和名称即可加入。</p>
      ) : (
        <section className={styles.list} aria-label="自选股列表">
          {items.map((item) => {
            const editing = editingCode === item.ts_code
            return (
              <article className={styles.item} key={item.ts_code}>
                <div className={styles.identity}>
                  <strong>{item.name}</strong>
                  <span>{item.ts_code}</span>
                </div>
                {editing ? (
                  <div className={styles.editor}>
                    <label>
                      <span>备注</span>
                      <textarea
                        aria-label={`${item.name}备注`}
                        value={note}
                        maxLength={2000}
                        onChange={(event) => setNote(event.target.value)}
                      />
                    </label>
                    <label className={styles.monitor}>
                      <button
                        type="button"
                        role="switch"
                        aria-label={`${item.name}监控`}
                        aria-checked={monitoring}
                        onClick={() => setMonitoring((value) => !value)}
                      >
                        <span />
                      </button>
                      <span>{monitoring ? '监控已开启' : '监控已关闭'}</span>
                    </label>
                  </div>
                ) : (
                  <div className={styles.summary}>
                    <p>{item.note || '暂无备注'}</p>
                    <span data-enabled={item.monitoring_enabled}>
                      {item.monitoring_enabled ? '监控中' : '未监控'}
                    </span>
                  </div>
                )}
                <div className={styles.actions}>
                  {editing ? (
                    <>
                      <button
                        type="button"
                        className={styles.primary}
                        aria-label={`保存 ${item.name}`}
                        disabled={savingCode === item.ts_code}
                        onClick={() => void saveItem(item)}
                      >
                        保存
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingCode(null)}
                      >
                        取消
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      aria-label={`编辑 ${item.name}`}
                      onClick={() => beginEdit(item)}
                    >
                      编辑
                    </button>
                  )}
                  <button
                    type="button"
                    className={styles.remove}
                    aria-label={`移除 ${item.name}`}
                    disabled={savingCode === item.ts_code}
                    onClick={() => void removeItem(item)}
                  >
                    移除
                  </button>
                </div>
              </article>
            )
          })}
        </section>
      )}
    </main>
  )
}
