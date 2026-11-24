import { describe, expect, it } from 'vitest'
import { applyEvent, buildItems, type Item, type Msg } from './messages'

const msg = (id: number, run_id: number | null, role: 'user' | 'assistant', content: unknown[]): Msg =>
  ({ id, run_id, role, content: JSON.stringify(content) })

const history: Msg[] = [
  msg(1, 1, 'user', [{ type: 'text', text: 'check TS3' }]),
  msg(2, 1, 'assistant', [{ type: 'text', text: 'on it' }, { type: 'tool_use', id: 'c1', name: 'wf', input: { system_name: 'TS3' } }]),
  msg(3, 1, 'user', [{ type: 'tool_result', tool_use_id: 'c1', content: '{"ok":1}', is_error: false }]),
  msg(4, 1, 'assistant', [{ type: 'text', text: 'done' }]),
]

describe('buildItems', () => {
  it('turns stored blocks into chat items and attaches tool results', () => {
    const items = buildItems(history)
    expect(items.map(i => i.kind)).toEqual(['user', 'assistant', 'tool', 'assistant'])
    const tool = items[2] as Extract<Item, { kind: 'tool' }>
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
})

describe('applyEvent', () => {
  it('appends text, starts a new text item after a tool card, tracks steps and end', () => {
    const items: Item[] = []
    applyEvent(items, { type: 'text', data: { text: 'he' } })
    applyEvent(items, { type: 'text', data: { text: 'llo' } })
    applyEvent(items, { type: 'tool_start', data: { workflow: 'wf', input: { a: 1 } } })
    applyEvent(items, { type: 'tool_step', data: { workflow: 'wf', task: 'sap.read_table', seq: 1, kind: 'task', status: 'running' } })
    applyEvent(items, { type: 'tool_step', data: { workflow: 'wf', task: 'sap.read_table', seq: 1, kind: 'task', status: 'ok' } })
    applyEvent(items, { type: 'waiting', data: { workflow: 'wf', resume_at: '2026-01-01T00:00:10+00:00' } })
    expect((items[1] as any).status).toBe('waiting')
    applyEvent(items, { type: 'tool_end', data: { workflow: 'wf', status: 'ok' } })
    applyEvent(items, { type: 'text', data: { text: 'next' } })
    expect(items.map(i => i.kind)).toEqual(['assistant', 'tool', 'assistant'])
    expect((items[0] as any).text).toBe('hello')
    const tool = items[1] as any
    expect(tool.status).toBe('ok')
    expect(tool.steps).toEqual([{ seq: 1, task: 'sap.read_table', status: 'ok' }])
  })
})
