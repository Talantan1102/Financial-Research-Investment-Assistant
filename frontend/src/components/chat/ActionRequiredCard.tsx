import { Link } from 'react-router-dom'
import type { ActionRequiredOutcome } from '@/api/runApi'
import styles from './ActionRequiredCard.module.scss'

interface ActionRequiredCardProps {
  outcome: ActionRequiredOutcome
  onContinue: (prompt: string) => void
}

export function ActionRequiredCard({ outcome, onContinue }: ActionRequiredCardProps) {
  const continuePrompt = `我已完成外部操作，请重新检查并继续：${outcome.intent_summary}`
  return (
    <section className={styles.card} aria-label="需要你完成的操作">
      <p className={styles.hint}>{outcome.resume_hint}</p>
      <Link className={styles.action} to={outcome.action_url}>{outcome.action_label}</Link>
      <button type="button" className={styles.continue} onClick={() => onContinue(continuePrompt)}>
        我已完成，继续
      </button>
    </section>
  )
}
