import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Input, Modal, Row, Spin, Statistic, Table, Tabs, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useSnapshot } from 'valtio'
import { listCashLedger, listFills, listHoldings, listOrders, getAccount, previewReset } from '@/api/paperTrading'
import type { PaperAccount, PaperCashLedgerEntry, PaperFill, PaperHolding, PaperOrder, ResetPreview } from '@/types/paper-trading'
import { paperTradingState } from '@/store/paper-trading'
import { PaperApprovalCard } from '@/components/chat/PaperApprovalCard'
import type { ChatMessage } from '@/types/chat'
import styles from './index.module.scss'

const statusLabel: Record<string, string> = { queued: '排队中', open: '开放', partially_filled: '部分成交', filled: '已成交', cancelled: '已撤销', expired: '已过期', rejected: '已拒绝', awaiting_confirmation: '待确认' }

export default function PaperTradingPage() {
  const approvals = useSnapshot(paperTradingState).approvals
  const [account, setAccount] = useState<PaperAccount | null>(null)
  const [holdings, setHoldings] = useState<PaperHolding[]>([])
  const [orders, setOrders] = useState<PaperOrder[]>([])
  const [fills, setFills] = useState<PaperFill[]>([])
  const [ledger, setLedger] = useState<PaperCashLedgerEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [resetOpen, setResetOpen] = useState(false)
  const [resetCash, setResetCash] = useState('1000000')
  const [resetPreviewData, setResetPreviewData] = useState<ResetPreview | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [a, h, o, f, l] = await Promise.all([getAccount(), listHoldings(), listOrders(), listFills(), listCashLedger()])
      setAccount(a); setHoldings(h); setOrders(o); setFills(f); setLedger(l)
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  const requestResetPreview = async () => {
    try { setResetPreviewData(await previewReset({ initial_cash: resetCash })) } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
  }
  const resetApproval = resetPreviewData ? {
    approval_id: `reset-${resetPreviewData.generation}-${resetPreviewData.account_id}`,
    approval_type: 'paper_reset' as const, resource_id: resetPreviewData.account_id,
    proposal: { initial_cash: resetPreviewData.replacement_initial_cash }, preview: resetPreviewData,
    expires_at: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
  } : null
  const resetMessage: ChatMessage | null = resetApproval ? {
    id: resetApproval.approval_id, session_id: 'paper-trading-page', role: 'assistant', content: '', message_type: 'paper_approval',
    research_report_id: null, research_report_summary: null, created_at: new Date().toISOString(), tool_call_data: resetApproval,
  } : null

  if (loading && !account) return <div style={{ padding: 40, textAlign: 'center' }}><Spin size="large" /></div>
  if (error && !account) return <div className={styles.page}><Alert type="error" showIcon message="加载模拟账户失败" description={error} /></div>

  const holdingColumns: ColumnsType<PaperHolding> = [
    { title: '股票', key: 'stock', render: (_, row) => `${row.name} (${row.ts_code})` },
    { title: '总持仓', dataIndex: 'quantity', render: (v: number) => v.toLocaleString() },
    { title: '可卖', dataIndex: 'sellable_quantity', render: (v: number) => <Tag color="green">可卖 {v.toLocaleString()}</Tag> },
    { title: '冻结', dataIndex: 'frozen_quantity' }, { title: '成本价', dataIndex: 'average_cost' },
  ]
  const orderColumns: ColumnsType<PaperOrder> = [
    { title: '股票', key: 'stock', render: (_, row) => `${row.name} (${row.ts_code})` }, { title: '方向', dataIndex: 'side', render: (v) => v === 'buy' ? '买入' : '卖出' }, { title: '数量', dataIndex: 'quantity' },
    { title: '状态', dataIndex: 'status', render: (v) => <Tag>{statusLabel[v] ?? v}</Tag> }, { title: '更新时间', dataIndex: 'completed_at', render: (v, row) => new Date(v ?? row.created_at).toLocaleString('zh-CN') },
  ]
  return <div className={styles.page}>
    <div className={styles.header}><div><h2>模拟账户</h2><span className={styles.muted}>第 {account?.generation} 代 · {account?.status}</span></div><Button danger onClick={() => { setResetOpen(true); setResetPreviewData(null) }}>重置账户</Button></div>
    {error ? <Alert closable type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
    <Row gutter={16} style={{ marginBottom: 20 }}><Col xs={24} sm={8}><Card><Statistic title="总资产" value={account?.initial_cash ?? '0.00'} precision={2} prefix="¥" /></Card></Col><Col xs={24} sm={8}><Card><Statistic title="可用资金" value={account?.available_cash ?? '0.00'} precision={2} prefix="¥" /></Card></Col><Col xs={24} sm={8}><Card><Statistic title="冻结资金" value={account?.frozen_cash ?? '0.00'} precision={2} prefix="¥" /></Card></Col></Row>
    <Tabs items={[{ key: 'holdings', label: '持仓', children: <Table rowKey="ts_code" columns={holdingColumns} dataSource={holdings} locale={{ emptyText: '暂无持仓' }} /> }, { key: 'orders', label: '订单', children: <Table rowKey="id" columns={orderColumns} dataSource={orders} locale={{ emptyText: '暂无订单' }} /> }, { key: 'fills', label: '成交', children: <Table rowKey="id" dataSource={fills} columns={[{ title: '数量', dataIndex: 'quantity' }, { title: '价格', dataIndex: 'price' }, { title: '成交时间', dataIndex: 'executed_at' }]} /> }, { key: 'ledger', label: '资金流水', children: <Table rowKey="id" dataSource={ledger} columns={[{ title: '类型', dataIndex: 'kind' }, { title: '金额', dataIndex: 'amount' }, { title: '时间', dataIndex: 'created_at' }]} /> }]} />
    {Object.values(approvals).filter((a) => a.approval_type === 'paper_reset').map((approval) => <div key={approval.approval_id} style={{ marginTop: 16 }}><PaperApprovalCard message={{ id: approval.approval_id, session_id: 'paper-trading-page', role: 'assistant', content: '', message_type: 'paper_approval', research_report_id: null, research_report_summary: null, created_at: new Date().toISOString(), tool_call_data: approval }} /></div>)}
    <Modal open={resetOpen} title="重置模拟账户" footer={null} onCancel={() => setResetOpen(false)}>{!resetPreviewData ? <><p>重置会归档当前账户并清空持仓、订单。请先预览。</p><Input value={resetCash} onChange={(e) => setResetCash(e.target.value)} addonBefore="初始资金" /><Button type="primary" style={{ marginTop: 16 }} onClick={() => void requestResetPreview()}>生成确认卡</Button></> : resetMessage ? <PaperApprovalCard message={resetMessage} /> : null}</Modal>
  </div>
}
