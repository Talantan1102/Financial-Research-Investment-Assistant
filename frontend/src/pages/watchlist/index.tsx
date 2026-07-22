import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, Switch, Table } from 'antd'
import { addWatchlist, listWatchlist, removeWatchlist, updateWatchlist, type WatchlistItem } from '@/api/watchlist'

export default function WatchlistPage() {
  const [items, setItems] = useState<WatchlistItem[]>([]); const [error, setError] = useState<string | null>(null); const [form] = Form.useForm()
  const refresh = () => listWatchlist().then(setItems).catch((e) => setError(String(e)))
  useEffect(() => { void refresh() }, [])
  const add = async (v: { ts_code: string; name: string }) => { await addWatchlist({ ...v, note: null, monitoring_enabled: false }); form.resetFields(); await refresh() }
  return <div style={{ padding: 24, maxWidth: 1000, margin: '0 auto' }}><h2>自选股</h2>{error ? <Alert type="error" message={error} /> : null}<Card title="添加自选股" style={{ marginBottom: 16 }}><Form form={form} layout="inline" onFinish={(v) => void add(v)}><Form.Item name="ts_code" rules={[{ required: true }]}><Input placeholder="股票代码" /></Form.Item><Form.Item name="name" rules={[{ required: true }]}><Input placeholder="股票名称" /></Form.Item><Button htmlType="submit" type="primary">添加</Button></Form></Card><Table rowKey="id" dataSource={items} columns={[{ title: '代码', dataIndex: 'ts_code' }, { title: '名称', dataIndex: 'name', render: (v, row) => <Input defaultValue={v} onBlur={(e) => { if (e.target.value !== v) void updateWatchlist(row.ts_code, { name: e.target.value }).then(refresh) }} /> }, { title: '备注', dataIndex: 'note', render: (v, row) => <Input defaultValue={v ?? ''} onBlur={(e) => { if (e.target.value !== (v ?? '')) void updateWatchlist(row.ts_code, { note: e.target.value || null }).then(refresh) }} /> }, { title: '监控', dataIndex: 'monitoring_enabled', render: (v, row) => <Switch checked={v} onChange={(checked) => void updateWatchlist(row.ts_code, { monitoring_enabled: checked }).then(refresh)} /> }, { title: '操作', render: (_, row) => <Button danger onClick={() => void removeWatchlist(row.ts_code).then(refresh)}>删除</Button> }]} /></div>
}
