import type { CSSProperties } from 'react'

export const sectionWrapper: CSSProperties = {
  marginBottom: 32,
}

export const sectionHeader: CSSProperties = {
  fontWeight: 600,
  fontSize: 15,
  marginBottom: 12,
  display: 'flex',
  alignItems: 'center',
  gap: 8,
}

export const itemRow: CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'flex-start',
  border: '1px solid var(--persona-border, #e0e0e0)',
  borderRadius: 6,
  padding: '10px 12px',
  marginBottom: 8,
  background: 'var(--persona-bg, #fff)',
  transition: 'background 200ms ease',
}

export const itemRowHighlighted: CSSProperties = {
  ...itemRow,
  background: 'rgba(245, 197, 24, 0.15)',
}

export const actions: CSSProperties = {
  display: 'flex',
  gap: 6,
  flexShrink: 0,
  marginLeft: 12,
}

export const emptyPlaceholder: CSSProperties = {
  color: '#999',
  fontStyle: 'italic',
  fontSize: 13,
  padding: '8px 12px',
}

export const fullEmpty: CSSProperties = {
  textAlign: 'center',
  padding: '40px 20px',
  color: '#666',
}
