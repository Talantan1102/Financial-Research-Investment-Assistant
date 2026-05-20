import styles from './Skeleton.module.scss'

export interface SkeletonProps {
  variant: 'list' | 'message' | 'card'
  count?: number
  height?: number
}

export function Skeleton({ variant, count = 3, height }: SkeletonProps) {
  const bars = Array.from({ length: count }, (_, i) => i)
  return (
    <div className={styles[variant]} data-testid={`skeleton-${variant}`} role="status" aria-live="polite">
      {bars.map((i) => (
        <div
          key={i}
          className={styles.bar}
          data-testid="skeleton-bar"
          style={height ? { height: `${height}px` } : undefined}
        />
      ))}
    </div>
  )
}
