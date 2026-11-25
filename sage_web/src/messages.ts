export interface Msg { id: number; run_id: number | null; role: 'user' | 'assistant'; content: string }

export interface CallDetail {
  id?: number; provider_call_id: string; workflow: string; status: string; started_at: string; ended_at: string | null
  system: { label: string; sid: string; client: string } | null
  steps: { seq: number; kind: string; attempt: number; name: string; status: string; created_at: string }[]
}
export interface RunDetail {
  run: { id: number; status: string; started_at: string; ended_at: string | null; resume_at: string | null; tokens_in: number; tokens_out: number; error: string | null }
  tool_calls: CallDetail[]
}

export type StepStatus = 'running' | 'waiting' | 'ok' | 'error'
export interface StepView { seq: number; task: string; status: StepStatus; attempts: number; at?: string; ms?: number }
export type ToolStatus = 'running' | 'waiting' | 'ok' | 'error'
export type ToolItem = {
  kind: 'tool'; id: string; callId?: number; name: string; input: any; output?: string; isError?: boolean
  status: ToolStatus; steps: StepView[]; runId?: number; system?: CallDetail['system']; startedAt?: string; endedAt?: string | null
}
export type Item = { kind: 'user'; text: string } | { kind: 'assistant'; text: string } | ToolItem

const ms = (a?: string, b?: string) => (a && b ? Date.parse(b) - Date.parse(a) : undefined)

/** One view row per workflow step. A polled step (a wait) counts its checks. */
export function groupSteps(rows: CallDetail['steps']): StepView[] {
  const out: StepView[] = [], bySeq = new Map<number, StepView>()
  for (const r of rows) {
    let s = bySeq.get(r.seq)
    if (!s) { s = { seq: r.seq, task: r.name, status: 'running', attempts: 0, at: r.created_at }; bySeq.set(r.seq, s); out.push(s) }
    if (r.kind === 'poll') s.attempts += 1
    s.status = r.status === 'ok' ? 'ok' : r.status === 'error' ? 'error' : 'running'
  }
  for (let i = 0; i < out.length - 1; i++) if (!out[i].attempts) out[i].ms = ms(out[i].at, out[i + 1].at)
  return out
}

export function buildItems(messages: Msg[], hideRunId: number | null = null, info: Record<number, RunDetail> = {}): Item[] {
  const items: Item[] = [], tools = new Map<string, ToolItem>()
  for (const m of messages) {
    const hide = hideRunId !== null && m.run_id === hideRunId && m.role === 'assistant'
    const hideResult = hideRunId !== null && m.run_id === hideRunId
    for (const b of JSON.parse(m.content) as any[]) {
      if (b.type === 'text' && m.role === 'user') items.push({ kind: 'user', text: b.text })
      else if (b.type === 'text' && !hide) items.push({ kind: 'assistant', text: b.text })
      else if (b.type === 'tool_use' && !hide) {
        const t: ToolItem = { kind: 'tool', id: b.id, name: b.name, input: b.input, status: 'running', steps: [], runId: m.run_id ?? undefined }
        const call = m.run_id != null ? info[m.run_id]?.tool_calls.find(c => c.provider_call_id === b.id) : undefined
        if (call) {
          t.callId = call.id; t.system = call.system; t.startedAt = call.started_at; t.endedAt = call.ended_at; t.steps = groupSteps(call.steps)
          if (call.status === 'waiting') {
            t.status = 'waiting'
            const polled = [...t.steps].reverse().find(s => s.attempts)
            if (polled) polled.status = 'waiting'
          }
        }
        tools.set(b.id, t); items.push(t)
      } else if (b.type === 'tool_result' && !hideResult) {
        const t = tools.get(b.tool_use_id)
        if (t) {
          t.output = b.content; t.isError = b.is_error; t.status = b.is_error ? 'error' : 'ok'
          for (const s of t.steps) if (s.status !== 'error') s.status = b.is_error && s === t.steps[t.steps.length - 1] ? 'error' : 'ok'
        }
      }
    }
  }
  return items
}

/** Apply one live run event to the item list (mutates; the list is a Vue ref). */
export function applyEvent(items: Item[], ev: { type: string; data: any; ts?: string }): void {
  const open = () => [...items].reverse().find((i): i is ToolItem => i.kind === 'tool' && (i.status === 'running' || i.status === 'waiting'))
  const d = ev.data
  if (ev.type === 'text') {
    const last = items[items.length - 1]
    if (last && last.kind === 'assistant') last.text += d.text
    else items.push({ kind: 'assistant', text: d.text })
  } else if (ev.type === 'tool_start') {
    items.push({ kind: 'tool', id: `live-${items.length}`, name: d.workflow, input: d.input, status: 'running', steps: [], startedAt: ev.ts })
  } else if (ev.type === 'tool_step') {
    const t = open()
    if (!t) return
    t.status = 'running'
    let s = t.steps.find(x => x.seq === d.seq)
    if (!s) {
      // a new step means the previous polled step finished waiting
      for (const p of t.steps) if (p.status === 'waiting') p.status = 'ok'
      s = { seq: d.seq, task: d.task, status: 'running', attempts: 0, at: ev.ts }
      t.steps.push(s)
    }
    if (d.kind === 'poll' && d.status === 'running') s.attempts += 1
    if (d.status === 'error') s.status = 'error'
    else if (d.status === 'ok' && d.kind !== 'poll') { s.status = 'ok'; s.ms = ms(s.at, ev.ts) }
    else s.status = 'running'
  } else if (ev.type === 'waiting') {
    const t = open()
    if (t) { t.status = 'waiting'; const p = [...t.steps].reverse().find(s => s.attempts); if (p) p.status = 'waiting' }
  } else if (ev.type === 'tool_end') {
    const t = open()
    if (t) { t.status = d.status === 'ok' ? 'ok' : 'error'; t.endedAt = ev.ts; for (const s of t.steps) if (s.status !== 'error') s.status = 'ok' }
  }
}
