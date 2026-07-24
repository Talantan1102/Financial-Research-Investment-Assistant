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
type MutationKind = 'add' | 'remove' | 'update'

export default function WatchlistPage() {
  const [items, setItems] = useState<WatchlistItem[]>([])
  const [loading, setLoading] = useState(true)
  const [listError, setListError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [adding, setAdding] = useState(false)
  const [editingCode, setEditingCode] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [monitoring, setMonitoring] = useState(false)
  const [, setPendingRevision] = useState(0)
  const codeVersions = useRef(new Map<string, number>())
  const codeGenerations = useRef(new Map<string, number>())
  const codeQueues = useRef(new Map<string, Promise<void>>())
  const lockedCodes = useRef(new Set<string>())
  const pendingOperations = useRef(new Set<string>())
  const activeListRequests = useRef(0)

  useEffect(() => {
    const baseline = beginListRequest()
    let active = true
    listWatchlist()
      .then((rows) => {
        if (active) {
          mergeServerRows(rows, baseline)
          setListError(null)
        }
      })
      .catch((reason) => {
        if (active) {
          setListError(
            `列表未完整加载：${
              reason instanceof Error ? reason.message : '自选股读取失败'
            }`,
          )
        }
      })
      .finally(() => {
        activeListRequests.current = Math.max(
          0,
          activeListRequests.current - 1,
        )
        if (
          activeListRequests.current === 0 &&
          codeQueues.current.size === 0 &&
          lockedCodes.current.size === 0 &&
          pendingOperations.current.size === 0
        ) {
          codeVersions.current.clear()
        }
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  function beginListRequest() {
    activeListRequests.current += 1
    return new Map(codeVersions.current)
  }

  function finishListRequest() {
    activeListRequests.current = Math.max(0, activeListRequests.current - 1)
    clearCodeVersionsIfSafe()
  }

  function clearCodeVersionsIfSafe() {
    if (
      activeListRequests.current === 0 &&
      codeQueues.current.size === 0 &&
      lockedCodes.current.size === 0 &&
      pendingOperations.current.size === 0
    ) {
      codeVersions.current.clear()
    }
  }

  function bumpCodeVersion(tsCode: string) {
    codeVersions.current.set(
      tsCode,
      (codeVersions.current.get(tsCode) ?? 0) + 1,
    )
  }

  function mergeServerRows(
    serverRows: WatchlistItem[],
    baseline: Map<string, number>,
  ) {
    const versionsAtMerge = new Map(codeVersions.current)
    setItems((current) => {
      const merged = serverRows.filter(
        (row) =>
          (versionsAtMerge.get(row.ts_code) ?? 0) ===
          (baseline.get(row.ts_code) ?? 0),
      )
      for (const item of current) {
        if (
          (versionsAtMerge.get(item.ts_code) ?? 0) !==
          (baseline.get(item.ts_code) ?? 0)
        ) {
          merged.push(item)
        }
      }
      return merged
    })
  }

  function retryList() {
    if (loading) return
    const baseline = beginListRequest()
    setLoading(true)
    void listWatchlist()
      .then((rows) => {
        mergeServerRows(rows, baseline)
        setListError(null)
      })
      .catch((reason) => {
        setListError(
          `列表未完整加载：${
            reason instanceof Error ? reason.message : '自选股读取失败'
          }`,
        )
      })
      .finally(() => {
        finishListRequest()
        setLoading(false)
      })
  }

  function isPending(tsCode: string, kind: MutationKind) {
    return pendingOperations.current.has(`${tsCode}:${kind}`)
  }

  function isCodeLocked(tsCode: string) {
    return lockedCodes.current.has(tsCode)
  }

  function enqueueMutation<T>(
    tsCode: string,
    kind: MutationKind,
    request: () => Promise<T>,
    apply: (result: T) => void,
    fallbackError: string,
    onSettled?: () => void,
  ) {
    const pendingKey = `${tsCode}:${kind}`
    if (lockedCodes.current.has(tsCode)) return false

    lockedCodes.current.add(tsCode)
    pendingOperations.current.add(pendingKey)
    setPendingRevision((value) => value + 1)
    bumpCodeVersion(tsCode)
    const generation = (codeGenerations.current.get(tsCode) ?? 0) + 1
    codeGenerations.current.set(tsCode, generation)
    setError(null)

    // One queue per symbol preserves user intent without blocking other symbols.
    const previous = codeQueues.current.get(tsCode) ?? Promise.resolve()
    const task = previous
      .catch(() => undefined)
      .then(async () => {
        try {
          const result = await request()
          if (codeGenerations.current.get(tsCode) === generation) {
            bumpCodeVersion(tsCode)
            apply(result)
          }
        } catch (reason) {
          if (codeGenerations.current.get(tsCode) === generation) {
            bumpCodeVersion(tsCode)
            let message =
              reason instanceof Error ? reason.message : fallbackError
            const baseline = beginListRequest()
            try {
              const serverItems = await listWatchlist()
              if (codeGenerations.current.get(tsCode) === generation) {
                mergeServerRows(serverItems, baseline)
                setListError(null)
                const serverItem = serverItems.find(
                  (item) => item.ts_code === tsCode,
                )
                if (!serverItem) {
                  setEditingCode((current) =>
                    current === tsCode ? null : current,
                  )
                }
              }
            } catch (reloadReason) {
              const reloadMessage =
                reloadReason instanceof Error
                  ? reloadReason.message
                  : '服务器状态重新读取失败'
              message = `${message}；重新读取失败：${reloadMessage}`
              setListError(`列表未完整加载：${reloadMessage}`)
            } finally {
              finishListRequest()
            }
            if (codeGenerations.current.get(tsCode) === generation) {
              setError(message)
            }
          }
        }
      })
      .finally(() => {
        if (codeGenerations.current.get(tsCode) === generation) {
          codeGenerations.current.delete(tsCode)
          lockedCodes.current.delete(tsCode)
          pendingOperations.current.delete(pendingKey)
          setPendingRevision((value) => value + 1)
          onSettled?.()
        }
        if (codeQueues.current.get(tsCode) === task) {
          codeQueues.current.delete(tsCode)
        }
        clearCodeVersionsIfSafe()
      })
    codeQueues.current.set(tsCode, task)
    return true
  }

  function addItem() {
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
    const queued = enqueueMutation(
      normalizedCode,
      'add',
      () =>
        addWatchlistItem({
          ts_code: normalizedCode,
          name: normalizedName,
          monitoring_enabled: false,
        }),
      (added) => {
        setItems((current) => {
          const withoutDuplicate = current.filter(
            (item) => item.ts_code !== added.ts_code,
          )
          return [...withoutDuplicate, added]
        })
        setCode('')
        setName('')
      },
      '加入自选失败',
      () => setAdding(false),
    )
    if (queued) setAdding(true)
  }

  function beginEdit(item: WatchlistItem) {
    setEditingCode(item.ts_code)
    setNote(item.note ?? '')
    setMonitoring(item.monitoring_enabled)
  }

  function saveItem(item: WatchlistItem) {
    enqueueMutation(
      item.ts_code,
      'update',
      () =>
        updateWatchlistItem(item.ts_code, {
          note: note.trim() || null,
          monitoring_enabled: monitoring,
        }),
      (saved) => {
        setItems((current) =>
          current.map((row) => (row.ts_code === saved.ts_code ? saved : row)),
        )
        setEditingCode((current) =>
          current === item.ts_code ? null : current,
        )
      },
      '保存自选股失败',
    )
  }

  function removeItem(item: WatchlistItem) {
    enqueueMutation(
      item.ts_code,
      'remove',
      () => removeWatchlistItem(item.ts_code),
      () => {
        setItems((current) =>
          current.filter((row) => row.ts_code !== item.ts_code),
        )
        if (editingCode === item.ts_code) setEditingCode(null)
      },
      '移除自选股失败',
    )
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p>WATCHLIST</p>
          <h1>自选股</h1>
          <span>持仓股票始终监控；开关只控制自选股来源。</span>
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
            disabled={isCodeLocked(code.trim().toUpperCase())}
          />
        </label>
        <label>
          <span>股票名称</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="贵州茅台"
            autoComplete="off"
            disabled={isCodeLocked(code.trim().toUpperCase())}
          />
        </label>
        <button
          type="button"
          onClick={() => void addItem()}
          disabled={adding || isCodeLocked(code.trim().toUpperCase())}
        >
          {adding ? '正在加入…' : '加入自选'}
        </button>
      </section>

      {error ? (
        <div className={styles.error} role="alert">
          {error}
        </div>
      ) : null}

      {listError ? (
        <div className={styles.error} role="alert">
          <span>{listError}</span>
          <button type="button" onClick={retryList} disabled={loading}>
            {loading ? '正在重新读取…' : '重新读取列表'}
          </button>
        </div>
      ) : null}

      {loading && items.length === 0 ? (
        <p className={styles.empty} aria-live="polite">
          正在读取自选股…
        </p>
      ) : (error || listError) && items.length === 0 ? null : items.length === 0 ? (
        <p className={styles.empty}>还没有自选股。输入代码和名称即可加入。</p>
      ) : (
        <section className={styles.list} aria-label="自选股列表">
          {items.map((item) => {
            const editing = editingCode === item.ts_code
            const locked = isCodeLocked(item.ts_code)
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
                        disabled={locked}
                        onChange={(event) => setNote(event.target.value)}
                      />
                    </label>
                    <label className={styles.monitor}>
                      <button
                        type="button"
                        role="switch"
                        aria-label={`${item.name}监控`}
                        aria-checked={monitoring}
                        disabled={locked}
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
                        disabled={locked || isPending(item.ts_code, 'update')}
                        onClick={() => void saveItem(item)}
                      >
                        保存
                      </button>
                      <button
                        type="button"
                        disabled={locked}
                        onClick={() => setEditingCode(null)}
                      >
                        取消
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      aria-label={`编辑 ${item.name}`}
                      disabled={locked}
                      onClick={() => beginEdit(item)}
                    >
                      编辑
                    </button>
                  )}
                  <button
                    type="button"
                    className={styles.remove}
                    aria-label={`移除 ${item.name}`}
                    disabled={locked || isPending(item.ts_code, 'remove')}
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
