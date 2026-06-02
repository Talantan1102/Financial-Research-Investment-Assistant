import { describe, expect, it } from 'vitest'
import { SLASH_COMMANDS, parseSlashInput } from '@/components/chat/slashCommands'

describe('slashCommands', () => {
  it('exposes the MVP commands', () => {
    const aliases = SLASH_COMMANDS.map((c) => c.alias)
    expect(aliases).toContain('/quote')
    expect(aliases).toContain('/kb')
    expect(aliases).toContain('/web')
  })

  it('parses /quote with a ts_code into a forced tool payload', () => {
    const r = parseSlashInput('/quote 600519.SH')
    expect(r).toEqual({
      kind: 'forced_tool',
      toolName: 'get_stock_quote',
      args: { ts_code: '600519.SH' },
      displayMessage: '/quote 600519.SH',
    })
  })

  it('parses /kb with a free-text query', () => {
    const r = parseSlashInput('/kb 茅台 估值')
    expect(r).toEqual({
      kind: 'forced_tool',
      toolName: 'kb_search',
      args: { query: '茅台 估值' },
      displayMessage: '/kb 茅台 估值',
    })
  })

  it('returns plain for non-slash text', () => {
    expect(parseSlashInput('hello world')).toEqual({ kind: 'plain' })
  })

  it('returns incomplete for a command with no argument', () => {
    expect(parseSlashInput('/quote')).toEqual({ kind: 'incomplete', alias: '/quote' })
  })

  it('returns menu for /tools (menu-only, not a forced tool)', () => {
    expect(parseSlashInput('/tools')).toEqual({ kind: 'menu' })
  })

  it('treats unknown slash as plain text', () => {
    expect(parseSlashInput('/bogus xyz')).toEqual({ kind: 'plain' })
  })
})
