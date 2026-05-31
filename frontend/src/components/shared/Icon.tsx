import type { CSSProperties } from 'react'

type IconName =
  | 'plus' | 'plus-circle' | 'search' | 'send' | 'stop' | 'arrow-up'
  | 'chevron-right' | 'chevron-down' | 'chevron-up' | 'check'
  | 'export' | 'edit' | 'more-horizontal' | 'close'
  | 'user-circle' | 'document' | 'bell' | 'book' | 'chart'
  | 'tool' | 'sparkle' | 'rocket' | 'log-out'

const PATHS: Record<IconName, string> = {
  'plus':         '<path d="M8 3v10M3 8h10" stroke-width="2.4"/>',
  'plus-circle':  '<circle cx="10" cy="10" r="8"/><path d="M10 6v8M6 10h8" stroke-width="1.8"/>',
  'search':       '<circle cx="7" cy="7" r="5"/><path d="M14 14l-3-3"/>',
  'send':         '<path d="M8 12V3M4 7l4-4 4 4"/>',
  'stop':         '<rect x="4" y="4" width="8" height="8" rx="1"/>',
  'arrow-up':     '<path d="M10 14V6M6 10l4-4 4 4"/>',
  'chevron-right': '<path d="M6 4l4 4-4 4"/>',
  'chevron-down': '<path d="M4 6l4 4 4-4"/>',
  'chevron-up':   '<path d="M4 10l4-4 4 4"/>',
  'check':        '<path d="M3 8l3 3 7-7"/>',
  'export':       '<path d="M10 13V3M6 8l4-5 4 5"/><path d="M4 14v2a1 1 0 001 1h10a1 1 0 001-1v-2"/>',
  'edit':         '<path d="M3 17h14M12 4l4 4-8 8H4v-4z"/>',
  'more-horizontal': '<circle cx="5" cy="10" r="1.5"/><circle cx="10" cy="10" r="1.5"/><circle cx="15" cy="10" r="1.5"/>',
  'close':        '<path d="M5 5l10 10M5 15L15 5"/>',
  'user-circle':  '<circle cx="10" cy="7" r="3"/><path d="M3 17c0-3.5 3-6 7-6s7 2.5 7 6"/><circle cx="10" cy="10" r="9"/>',
  'document':     '<path d="M5 3h7l3 3v11H5z M12 3v3h3 M7 10h6 M7 13h4"/>',
  'bell':         '<path d="M10 2v8l5 3"/><circle cx="10" cy="10" r="8"/>',
  'book':         '<path d="M4 4h12v12H4z M4 8h12"/>',
  'chart':        '<path d="M3 13L8 3l5 10M5 9h6"/>',
  'tool':         '<path d="M3 13L8 3l5 10M5 9h6"/>',
  'sparkle':      '<path d="M10 2l2 6 6 2-6 2-2 6-2-6-6-2 6-2z"/>',
  'rocket':       '<path d="M14 6l-8 8M14 6h-4M14 6v4M6 14l-3 3M10 10l4 4"/>',
  'log-out':      '<path d="M11 3H5a2 2 0 00-2 2v10a2 2 0 002 2h6M15 11l4-4-4-4M19 7H9"/>',
}

export interface IconProps {
  name: IconName
  size?: number
  style?: CSSProperties
  className?: string
  'aria-hidden'?: boolean
}

export function Icon({ name, size = 16, style, className, ...rest }: IconProps) {
  const inner = PATHS[name]
  const viewBox = name === 'user-circle' || name === 'plus-circle' ? '0 0 20 20' :
                  name === 'export' || name === 'edit' || name === 'document' ||
                  name === 'book' || name === 'chart' || name === 'tool' ||
                  name === 'sparkle' || name === 'rocket' || name === 'arrow-up' ||
                  name === 'bell' || name === 'more-horizontal' ||
                  name === 'log-out' ? '0 0 20 20' : '0 0 16 16'
  return (
    <svg
      width={size} height={size} viewBox={viewBox}
      fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round"
      style={style} className={className}
      aria-hidden={rest['aria-hidden'] ?? true}
      dangerouslySetInnerHTML={{ __html: inner }}
    />
  )
}

export type { IconName }
