const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''

export interface ToolMeta {
  name: string
  description: string
  inputSchema: Record<string, unknown>
}

export async function fetchTools(): Promise<ToolMeta[]> {
  const base = (API_BASE ?? '').replace(/\/$/, '')
  const res = await fetch(`${base}/api/v0/tools`)
  if (!res.ok) return []
  const body = (await res.json()) as { tools: ToolMeta[] }
  return body.tools ?? []
}
