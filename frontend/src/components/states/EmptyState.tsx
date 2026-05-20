import type { ReactNode } from 'react'
import { Icon, type IconName } from '@/components/shared/Icon'
import styles from './EmptyState.module.scss'

export interface EmptyStateProps {
  variant: 'chat-empty' | 'list-empty' | 'search-empty'
  title: string
  description?: string
  cta?: { label: string; onClick: () => void; primary?: boolean }
  icon?: ReactNode
}

const DEFAULT_ICON: Record<EmptyStateProps['variant'], IconName> = {
  'chat-empty': 'sparkle',
  'list-empty': 'document',
  'search-empty': 'search',
}

export function EmptyState({ variant, title, description, cta, icon }: EmptyStateProps) {
  return (
    <div className={styles.empty} data-testid={`empty-${variant}`} role="region">
      <div className={styles.icon}>
        {icon ?? <Icon name={DEFAULT_ICON[variant]} size={32} />}
      </div>
      <div className={styles.title}>{title}</div>
      {description ? <div className={styles.desc}>{description}</div> : null}
      {cta ? (
        <button
          type="button"
          className={`${styles.cta} ${cta.primary ? styles.primary : ''}`}
          onClick={cta.onClick}
        >
          {cta.label}
        </button>
      ) : null}
    </div>
  )
}
