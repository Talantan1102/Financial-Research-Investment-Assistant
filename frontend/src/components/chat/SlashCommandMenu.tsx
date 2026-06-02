import { Command } from 'cmdk'
import { SLASH_COMMANDS } from '@/components/chat/slashCommands'
import styles from '@/styles/chat.module.scss'

export interface SlashCommandMenuProps {
  open: boolean
  query: string // current input value, e.g. "/qu"
  onSelect: (alias: string) => void
}

export function SlashCommandMenu(props: SlashCommandMenuProps) {
  if (!props.open) return null
  // strip leading slash; we pass our own filtered list (cmdk's own filter disabled)
  const q = props.query.replace(/^\//, '').toLowerCase()
  const items = SLASH_COMMANDS.filter((c) => c.alias.slice(1).toLowerCase().startsWith(q))
  if (items.length === 0) return null

  return (
    <div className={styles.slashMenu} role="listbox" aria-label="斜杠命令">
      <Command shouldFilter={false}>
        <Command.List>
          {items.map((c) => (
            <Command.Item key={c.alias} value={c.alias} onSelect={() => props.onSelect(c.alias)}>
              <span className={styles.slashAlias}>{c.alias}</span>
              <span className={styles.slashLabel}>{c.label}</span>
              <span className={styles.slashHint}>{c.hint}</span>
            </Command.Item>
          ))}
        </Command.List>
      </Command>
    </div>
  )
}
