import { Icon } from '@/components/shared/Icon'
import styles from './ErrorState.module.scss'

export interface ErrorStateProps {
  title?: string
  description?: string
  onRetry?: () => void
  onReset?: () => void
}

export function ErrorState({
  title = '出错了',
  description,
  onRetry,
  onReset,
}: ErrorStateProps) {
  return (
    <div className={styles.error} data-testid="error-state" role="alert">
      <div className={styles.icon}>
        <Icon name="close" size={20} />
      </div>
      <div className={styles.title}>{title}</div>
      {description ? <div className={styles.desc}>{description}</div> : null}
      {(onRetry || onReset) ? (
        <div className={styles.actions}>
          {onRetry ? (
            <button
              type="button"
              className={`${styles.btn} ${styles.primary}`}
              onClick={onRetry}
            >
              重试
            </button>
          ) : null}
          {onReset ? (
            <button
              type="button"
              className={styles.btn}
              onClick={onReset}
            >
              重置
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
