/**
 * ReportOutline.tsx
 * Left sticky outline for D output report view.
 * Renders § 1-§ 6 anchor links; clicking scrolls to the section.
 *
 * SECTION_ANCHORS is in sectionAnchors.ts (separated for react-refresh compat).
 */

import { SECTION_ANCHORS } from './sectionAnchors'

// ── Design tokens ─────────────────────────────────────────────────────────────
const TOKEN = {
  cardBg: '#ffffff',
  borderColor: '#e8e4dc',
  textSecondary: '#5d6875',
  textTertiary: '#8a96a3',
  accentBlue: '#1d4ed8',
}

// ── Props ─────────────────────────────────────────────────────────────────────
interface ReportOutlineProps {
  style?: React.CSSProperties
  className?: string
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function ReportOutline({ style, className }: ReportOutlineProps) {
  const scrollTo = (id: string) => {
    const el = document.getElementById(id)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  return (
    <div
      className={className}
      style={{
        backgroundColor: TOKEN.cardBg,
        border: `1px solid ${TOKEN.borderColor}`,
        borderRadius: 10,
        padding: '16px 0',
        position: 'sticky',
        top: 16,
        ...style,
      }}
    >
      <div
        style={{
          fontSize: 12,
          color: TOKEN.textTertiary,
          fontWeight: 600,
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          padding: '0 16px',
          marginBottom: 8,
        }}
      >
        目录
      </div>
      {SECTION_ANCHORS.map((sec) => (
        <button
          key={sec.id}
          onClick={() => scrollTo(sec.id)}
          style={{
            display: 'block',
            width: '100%',
            textAlign: 'left',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            padding: '7px 16px',
            fontSize: 13,
            color: TOKEN.textSecondary,
            transition: 'color 0.15s, background 0.15s',
            borderRadius: 0,
          }}
          onMouseEnter={(e) => {
            ;(e.currentTarget as HTMLButtonElement).style.color = TOKEN.accentBlue
            ;(e.currentTarget as HTMLButtonElement).style.backgroundColor = 'rgba(29,78,216,0.04)'
          }}
          onMouseLeave={(e) => {
            ;(e.currentTarget as HTMLButtonElement).style.color = TOKEN.textSecondary
            ;(e.currentTarget as HTMLButtonElement).style.backgroundColor = ''
          }}
        >
          {sec.label}
        </button>
      ))}
    </div>
  )
}
