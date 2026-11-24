import { describe, expect, it } from 'vitest'
import { applyEvent, buildItems, groupSteps, type Item, type Msg, type RunDetail, type ToolItem } from './messages'

const msg = (id: number, run_id: number | null, role: 'user' | 'assistant', content: unknown[]): Msg =>
  ({ id, run_id, role, content: JSON.stringify(content) })

const history: Msg[] = [
  msg(1, 1, 'user', [{ type: 'text', text: 'check TS3' }]),
  msg(2, 1, 'assistant', [{ type: 'text', text: 'on it' }, { type: 'tool_use', id: 'c1', name: 'wf', input: { system_name: 'TS3' } }]),
  msg(3, 1, 'user', [{ type: 'tool_result', tool_use_id: 'c1', content: '{"ok":1}', is_error: false }]),
  msg(4, 1, 'assistant', [{ type: 'text', text: 'done' }]),
]

const row = (seq: number, kind: string, attempt: number, name: string, status: string, at: string) =>
  ({ seq, kind, attempt, name, status, created_at: at })

describe('buildItems', () => {
  it('turns stored blocks into chat items and attaches tool results', () => {
    const items = buildItems(history)
    expect(items.map(i => i.kind)).toEqual(['user', 'assistant', 'tool', 'assistant'])
    const tool = items[2] as ToolItem
    expect(tool.status).toBe('ok')
    expect(tool.output).toBe('{"ok":1}')
  })
  it('marks a failed tool result as error', () => {
    const m = [...history]
    m[2] = msg(3, 1, 'user', [{ type: 'tool_result', tool_use_id: 'c1', content: 'boom', is_error: true }])
    expect((buildItems(m)[2] as any).status).toBe('error')
  })
  it('hides the active run but keeps its user text (it is rebuilt from events)', () => {
    expect(buildItems(history, 1).map(i => i.kind)).toEqual(['user'])
  })
  it('adds system, steps and the waiting state from run details', () => {
    const info: Record<number, RunDetail> = {
      1: {
        run: { id: 1, status: 'waiting', started_at: 'a', ended_at: null, resume_at: 'x', tokens_in: 5, tokens_out: 2, error: null },
        tool_calls: [{
          provider_call_id: 'c1', workflow: 'wf', status: 'waiting', started_at: '2026-01-01T00:00:00+00:00', ended_at: null,
          system: { label: 'TS3', sid: 'S4H', client: '100' },
          steps: [row(1, 'task', 0, 'rc.start_analysis', 'ok', '2026-01-01T00:00:00+00:00'),
                  row(2, 'poll', 0, 'sap.job_status', 'ok', '2026-01-01T00:00:03+00:00'),
                  row(2, 'poll', 1, 'sap.job_status', 'ok', '2026-01-01T00:05:03+00:00')],
        }],
      },
    }
    const t = buildItems(history.slice(0, 2), null, info)[2] as ToolItem
    expect(t.system?.label).toBe('TS3')
    expect(t.status).toBe('waiting')
    expect(t.steps.map(s => [s.task, s.status, s.attempts])).toEqual([['rc.start_analysis', 'ok', 0], ['sap.job_status', 'waiting', 2]])
    expect(t.steps[0].ms).toBe(3000)
  })
})

describe('groupSteps', () => {
  it('counts checks of a polled step and keeps one row per step', () => {
    const g = groupSteps([row(1, 'poll', 0, 'p', 'ok', 'a'), row(1, 'poll', 1, 'p', 'running', 'b')])
    expect(g).toHaveLength(1)
    expect(g[0]).toMatchObject({ attempts: 2, status: 'running' })
  })
})

describe('applyEvent', () => {
  it('appends text, starts a new text item after a tool card, tracks steps, timing and end', () => {
    const items: Item[] = []
    applyEvent(items, { type: 'text', data: { text: 'he' } })
    applyEvent(items, { type: 'text', data: { text: 'llo' } })
    applyEvent(items, { type: 'tool_start', data: { workflow: 'wf', input: { a: 1 } }, ts: '2026-01-01T00:00:00+00:00' })
    applyEvent(items, { type: 'tool_step', data: { workflow: 'wf', task: 'sap.read_table', seq: 1, kind: 'task', status: 'running' }, ts: '2026-01-01T00:00:01+00:00' })
    applyEvent(items, { type: 'tool_step', data: { workflow: 'wf', task: 'sap.read_table', seq: 1, kind: 'task', status: 'ok' }, ts: '2026-01-01T00:00:03+00:00' })
    applyEvent(items, { type: 'tool_step', data: { workflow: 'wf', task: 'sap.job_status', seq: 2, kind: 'poll', status: 'running' }, ts: '2026-01-01T00:00:04+00:00' })
    applyEvent(items, { type: 'tool_step', data: { workflow: 'wf', task: 'sap.job_status', seq: 2, kind: 'poll', status: 'ok' }, ts: '2026-01-01T00:00:05+00:00' })
    applyEvent(items, { type: 'waiting', data: { workflow: 'wf', resume_at: '2026-01-01T00:00:10+00:00' } })
    const tool = items[1] as ToolItem
    expect(tool.status).toBe('waiting')
    expect(tool.steps.map(s => [s.seq, s.status, s.attempts, s.ms])).toEqual([[1, 'ok', 0, 2000], [2, 'waiting', 1, undefined]])
    applyEvent(items, { type: 'tool_end', data: { workflow: 'wf', status: 'ok' }, ts: '2026-01-01T00:10:00+00:00' })
    applyEvent(items, { type: 'text', data: { text: 'next' } })
    expect(items.map(i => i.kind)).toEqual(['assistant', 'tool', 'assistant'])
    expect((items[0] as any).text).toBe('hello')
    expect(tool.status).toBe('ok')
    expect(tool.steps.every(s => s.status === 'ok')).toBe(true)
  })
})
