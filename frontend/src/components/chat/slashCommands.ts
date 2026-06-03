// MVP slash commands — inline single-required-param MCP tools only.
// (get_financial_statements/get_market_indicators/get_corporate_actions need a
//  2nd required enum arg, compare_stocks needs a list arg → modal, all deferred.
//  get_news has no free-text query param → deferred to the modal follow-up.)

export interface SlashCommand {
  alias: string // user types this, e.g. "/quote"
  toolName: string // real MCP tool name
  paramKey: string // single arg key fed to the tool
  label: string // menu label
  hint: string // argument hint shown in the menu
}

export const SLASH_COMMANDS: SlashCommand[] = [
  {
    alias: '/quote',
    toolName: 'get_stock_quote',
    paramKey: 'ts_code',
    label: '实时行情',
    hint: '<ts_code> 如 600519.SH',
  },
  { alias: '/kb', toolName: 'kb_search', paramKey: 'query', label: '知识库检索', hint: '<查询词>' },
  { alias: '/web', toolName: 'web_search', paramKey: 'query', label: '联网搜索', hint: '<查询词>' },
]

// "/tools" is the menu itself, not a forced tool.
export const MENU_ALIAS = '/tools'

export type ParseResult =
  | { kind: 'plain' }
  | { kind: 'menu' }
  | { kind: 'incomplete'; alias: string }
  | {
      kind: 'forced_tool'
      toolName: string
      args: Record<string, string>
      displayMessage: string
    }

export function parseSlashInput(raw: string): ParseResult {
  const text = raw.trim()
  if (!text.startsWith('/')) return { kind: 'plain' }
  if (text === MENU_ALIAS) return { kind: 'menu' }

  const spaceIdx = text.indexOf(' ')
  const alias = (spaceIdx === -1 ? text : text.slice(0, spaceIdx)).toLowerCase()
  const cmd = SLASH_COMMANDS.find((c) => c.alias === alias)
  if (!cmd) return { kind: 'plain' } // unknown slash → treat as normal text

  const arg = spaceIdx === -1 ? '' : text.slice(spaceIdx + 1).trim()
  if (!arg) return { kind: 'incomplete', alias }

  return {
    kind: 'forced_tool',
    toolName: cmd.toolName,
    args: { [cmd.paramKey]: arg },
    displayMessage: text,
  }
}
