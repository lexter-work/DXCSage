export interface Msg { id: number; run_id: number | null; role: 'user' | 'assistant'; content: string }
export type ToolItem = {
  kind: 'tool'; id: string; name: string; input: any; output?: string; isError?: boolean
  status: 'running' | 'waiting' | 'ok' | 'error'; steps: { seq: number; task: string; status: string }[]
}
export type Item = { kind: 'user'; text: string } | { kind: 'assistant'; text: string } | ToolItem

export function buildItems(messages: Msg[], hideRunId: number | null = null): Item[] {
  const items: Item[] = [], tools = new Map<string, ToolItem>()
  for (const m of messages) {
    const hide = hideRunId !== null && m.run_id === hideRunId && m.role === 'assistant'
    const hideResult = hideRunId !== null && m.run_id === hideRunId
    for (const b of JSON.parse(m.content) as any[]) {
      if (b.type === 'text' && m.role === 'user') items.push({ kind: 'user', text: b.text })
      else if (b.type === 'text' && !hide) items.push({ kind: 'assistant', text: b.text })
      else if (b.type === 'tool_use' && !hide) {
        const t: ToolItem = { kind: 'tool', id: b.id, name: b.name, input: b.input, status: 'running', steps: [] }
        tools.set(b.id, t); items.push(t)
      } else if (b.type === 'tool_result' && !hideResult) {
        const t = tools.get(b.tool_use_id)
        if (t) { t.output = b.content; t.isError = b.is_error; t.status = b.is_error ? 'error' : 'ok' }
      }
    }
  }
  return items
}

/** Apply one live run event to the item list (mutates; the list is a Vue ref). */
export function applyEvent(items: Item[], ev: { type: string; data: any }): void {
  const lastTool = () => [...items].reverse().find((i): i is ToolItem => i.kind === 'tool' && i.status !== 'ok' && i.status !== 'error')
  const d = ev.data
  if (ev.type === 'text') {
    const last = items[items.length - 1]
    if (last && last.kind === 'assistant') last.text += d.text
    else items.push({ kind: 'assistant', text: d.text })
  } else if (ev.type === 'tool_start') {
    items.push({ kind: 'tool', id: `live-${items.length}`, name: d.workflow, input: d.input, status: 'running', steps: [] })
  } else if (ev.type === 'tool_step') {
    const t = lastTool()
    if (!t) return
    const s = t.steps.find(x => x.seq === d.seq)
    if (s) s.status = d.status
    else t.steps.push({ seq: d.seq, task: d.task, status: d.status })
  } else if (ev.type === 'waiting') {
    const t = lastTool(); if (t) t.status = 'waiting'
  } else if (ev.type === 'tool_end') {
    const t = lastTool(); if (t) { t.status = d.status === 'ok' ? 'ok' : 'error' }
  }
}
