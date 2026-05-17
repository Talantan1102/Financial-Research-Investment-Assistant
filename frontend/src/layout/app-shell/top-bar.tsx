import { Link } from 'react-router-dom'
import { Button } from 'antd'

export function TopBar() {
  return (
    <div
      style={{
        height: 56,
        display: 'flex',
        alignItems: 'center',
        padding: '0 16px',
        borderBottom: '1px solid #eee',
        gap: 12,
        fontWeight: 600,
      }}
    >
      <span>Financial Research Assistant</span>
      <span style={{ flex: 1 }} />
      <Link to="/memory#persona">
        <Button type="text" size="small">📋 我的画像</Button>
      </Link>
    </div>
  )
}
