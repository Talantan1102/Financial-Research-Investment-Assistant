import styles from './LoadingDots.module.scss'

export function LoadingDots({ ariaLabel = 'Loading' }: { ariaLabel?: string }) {
  return (
    <span className={styles.dots} role="status" aria-label={ariaLabel}>
      <span></span>
      <span></span>
      <span></span>
    </span>
  )
}
