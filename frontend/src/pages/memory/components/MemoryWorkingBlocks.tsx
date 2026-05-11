import { useEffect, useState } from 'react'
import { Card, Empty, Skeleton, Tag } from 'antd'
import { fetchMemoryBlocks } from '@/api/memoryApi'
import type { WorkingBlock } from '@/types/memory'

/**
 * MemoryWorkingBlocks — 只读 working memory 卡片 (Plan 7A).
 *
 * 显示 persona / scratchpad 当前内容 + token 消耗.
 * 编辑 / 替换 留 Plan 7B (#8 chat-side 改造).
 */
export function MemoryWorkingBlocks() {
  const [blocks, setBlocks] = useState<WorkingBlock[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    fetchMemoryBlocks()
      .then((res) => {
        if (alive) setBlocks(res.blocks)
      })
      .catch((e: Error) => {
        if (alive) setError(e.message)
      })
    return () => {
      alive = false
    }
  }, [])

  if (error) {
    return (
      <Card title="Working Memory" size="small">
        <span style={{ color: '#c0392b' }}>load failed: {error}</span>
      </Card>
    )
  }
  if (blocks === null) {
    return (
      <Card title="Working Memory" size="small">
        <Skeleton active paragraph={{ rows: 2 }} />
      </Card>
    )
  }
  if (blocks.length === 0) {
    return (
      <Card title="Working Memory" size="small">
        <Empty description="no working blocks yet" />
      </Card>
    )
  }

  return (
    <Card title="Working Memory" size="small" data-testid="memory-blocks-card">
      {blocks.map((b) => (
        <div key={b.block_name} style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <strong>{b.block_name}</strong>
            <Tag color="default">
              {b.token_count} / {b.max_tokens} tokens
            </Tag>
          </div>
          <pre
            style={{
              background: '#f7f6f4',
              padding: 8,
              borderRadius: 4,
              fontSize: 12,
              whiteSpace: 'pre-wrap',
              marginTop: 4,
            }}
          >
            {b.content || '(empty)'}
          </pre>
        </div>
      ))}
    </Card>
  )
}
