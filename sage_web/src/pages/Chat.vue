<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { del, get, patch, post } from '../api'
import { applyEvent, buildItems, type Item, type Msg, type RunDetail, type ToolItem } from '../messages'
import { layout, toggleThreads, setThreadsCollapsed } from '../layout'
import ConfirmModal from '../components/ConfirmModal.vue'
import StatusPill from '../components/StatusPill.vue'
import Icon from '../components/Icon.vue'
import { toast } from '../toast'

const PROVIDER_NAMES: Record<string, string> = { anthropic: 'Claude', openai: 'GPT' }
const pname = (p: string) => PROVIDER_NAMES[p] ?? p

const chats = ref<any[]>([]), current = ref<any | null>(null), items = ref<Item[]>([])
const providers = ref<Record<string, string[]>>({}), provider = ref(''), model = ref('')
const text = ref(''), activeRun = ref<number | null>(null), resumeAt = ref<string | null>(null)
const confirmDel = ref<any | null>(null), runInfo = ref<Record<number, RunDetail>>({})
const thopen = ref(false), listEl = ref<HTMLElement | null>(null), openBtn = ref<HTMLElement | null>(null)
const now = ref(Date.now())
let es: EventSource | null = null, lastEvent = 0, retry: number | undefined, tick: number | undefined, messages: Msg[] = []

const small = window.matchMedia('(max-width:1000px)')
const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
const hm = (iso?: string | null, sec = false) => iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', ...(sec ? { second: '2-digit' } : {}), hour12: false }) : '—'
const dur = (a?: string | null, b?: string | null) => {
  if (!a) return '—'
  const s = Math.max(0, Math.round(((b ? Date.parse(b) : now.value) - Date.parse(a)) / 1000))
  return s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m` : s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`
}
const stepMs = (ms?: number) => ms == null ? '' : ms < 60000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms / 60000)}m`
const k = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
const tokens = (it: ToolItem) => { const r = it.runId != null ? runInfo.value[it.runId]?.run : null; return r ? `${k(r.tokens_in)} / ${k(r.tokens_out)}` : '—' }

const dotOf = (s?: string) => s === 'waiting' || s === 'running' ? 'warn' : s === 'done' ? 'ok' : s === 'failed' ? 'bad' : 'off'
const subOf = (c: any) => `${{ waiting: 'Waiting for a workflow', running: 'Running', done: 'Done', failed: 'Failed', cancelled: 'Cancelled' }[c.last_run_status as string] ?? 'No messages yet'} · ${c.model}`
const groups = computed(() => {
  const day = (c: any) => Math.floor((Date.now() - Date.parse(c.created_at)) / 86400000)
  const g = [['Today', chats.value.filter(c => day(c) < 1)], ['This week', chats.value.filter(c => day(c) >= 1 && day(c) < 7)], ['Earlier', chats.value.filter(c => day(c) >= 7)]] as const
  return g.filter(([, l]) => l.length)
})

async function loadChats() { chats.value = await get('api/chats') }
async function loadRunInfo(id: number) {
  try { runInfo.value[id] = await get(`api/runs/${id}`) } catch { return /* run info is a nicety */ }
  // Live cards come from events, which carry no system; match them to the stored calls in order.
  const calls = runInfo.value[id].tool_calls
  items.value.filter((i): i is ToolItem => i.kind === 'tool' && i.id.startsWith('live-') && i.runId === id)
    .forEach((it, n) => { const c = calls[n]; if (c) { it.callId = c.id; it.system = c.system; it.startedAt ??= c.started_at } })
}
function rebuild() { items.value = buildItems(messages, activeRun.value, runInfo.value) }
async function loadMessages() {
  if (!current.value) return
  messages = await get(`api/chats/${current.value.id}/messages`)
  const ids = [...new Set(messages.map(m => m.run_id).filter((x): x is number => x != null))]
  await Promise.all(ids.map(loadRunInfo))
  rebuild()
}
function closeStream() { es?.close(); es = null; clearTimeout(retry) }
function startTick() { clearInterval(tick); tick = window.setInterval(() => (now.value = Date.now()), 1000) }

function attach(runId: number, after = 0) {
  closeStream()
  activeRun.value = runId; lastEvent = after
  if (after === 0) rebuild()
  loadRunInfo(runId)
  es = new EventSource(`api/runs/${runId}/events?after=${lastEvent}`)
  es.onmessage = async (e) => {
    lastEvent = Number(e.lastEventId) || lastEvent
    const ev = JSON.parse(e.data)
    if (ev.type === 'waiting') resumeAt.value = ev.data.resume_at
    if (ev.type === 'tool_end') resumeAt.value = null
    if (['done', 'error', 'cancelled'].includes(ev.type)) {
      closeStream(); activeRun.value = null; resumeAt.value = null
      if (ev.type === 'error') toast(ev.data.error || 'The run failed.')
      await loadMessages(); await loadChats(); return
    }
    applyEvent(items.value, ev)
    for (const it of items.value) if (it.kind === 'tool' && it.runId == null) it.runId = runId
    if (['tool_start', 'tool_end', 'waiting'].includes(ev.type)) loadRunInfo(runId)
  }
  // EventSource reconnects with Last-Event-ID, not our ?after=, so reopen by hand.
  es.onerror = () => { if (activeRun.value === runId) { es?.close(); retry = window.setTimeout(() => attach(runId, lastEvent), 1000) } }
}

async function select(c: any) {
  closeStream(); activeRun.value = null; resumeAt.value = null; current.value = c
  await loadMessages()
  if (['running', 'waiting'].includes(c.last_run_status)) attach(c.last_run_id)
  if (small.matches) thopen.value = false
}
const creatingChat = ref(false)
async function newChat() {
  if (!provider.value || !model.value) return toast('Choose a provider and model first.')
  creatingChat.value = true
  try {
    const { id } = await post('api/chats', { provider: provider.value, model: model.value })
    await loadChats(); setThreadsCollapsed(false); await select(chats.value.find(c => c.id === id))
  } catch (e) { toast(e) } finally { creatingChat.value = false }
}
async function changeModel() {
  if (!current.value) return
  try { await patch(`api/chats/${current.value.id}`, { provider: current.value.provider, model: current.value.model }) } catch (e) { toast(e) }
}
// Excel change requests: attach a file (or just describe the changes in the message), and download a template.
const pending = ref<any[]>([]), fileInput = ref<HTMLInputElement | null>(null), uploading = ref(false)
const templates = [['user_roles', 'User roles (assign or unassign)'], ['role_auth', 'Role authorizations'], ['tcode_removal', 'Remove transaction codes']]
async function onFiles(e: Event) {
  const input = e.target as HTMLInputElement
  if (!current.value || !input.files?.length) return
  uploading.value = true
  try {
    for (const f of Array.from(input.files)) {
      const r = await fetch(`api/chats/${current.value.id}/uploads?filename=${encodeURIComponent(f.name)}`, { method: 'PUT', credentials: 'same-origin', body: f })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) { toast(j.detail ?? 'The upload failed.'); continue }
      pending.value.push(j)
    }
  } finally { uploading.value = false; input.value = '' }
}
const summary = (f: any) => (f.kind ? `${f.kind_title}: ${f.rows} row(s)` + (f.error_count ? `, ${f.error_count} row error(s)` : '') : 'layout not recognised')
async function send() {
  if (!current.value || !text.value.trim() || activeRun.value) return
  const t = text.value; text.value = ''
  const files = pending.value; pending.value = []
  try {
    const { run_id } = await post(`api/chats/${current.value.id}/runs`, { text: t, files: files.map(f => f.id) })
    messages = await get(`api/chats/${current.value.id}/messages`)
    attach(run_id)
  } catch (e) { text.value = t; pending.value = files; toast(e) }
}
function onKey(e: KeyboardEvent) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }
const cancelling = ref(false)
async function cancel() {
  if (!activeRun.value) return
  cancelling.value = true
  try { await post(`api/runs/${activeRun.value}/cancel`) } catch (e) { toast(e) } finally { cancelling.value = false }
}
async function remove() {
  const c = confirmDel.value; confirmDel.value = null
  await del(`api/chats/${c.id}`).catch(toast)
  if (current.value?.id === c.id) { current.value = null; items.value = []; closeStream(); activeRun.value = null }
  await loadChats()
}

watch(thopen, async (o) => {
  if (o) { await nextTick(); (listEl.value?.querySelector<HTMLElement>('.thread[aria-current="true"]') ?? listEl.value?.querySelector<HTMLElement>('.thclose'))?.focus() }
  else if (small.matches) openBtn.value?.focus()
})
const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape' && thopen.value) thopen.value = false }
const onSmall = () => { if (!small.matches) thopen.value = false }
const busy = computed(() => items.value.some(i => i.kind === 'tool' && (i.status === 'running' || i.status === 'waiting')))
watch(busy, (b) => { if (b) startTick(); else clearInterval(tick) })

onMounted(async () => {
  window.addEventListener('keydown', onEsc); small.addEventListener('change', onSmall)
  providers.value = await get('api/providers')
  provider.value = Object.keys(providers.value)[0] ?? ''
  model.value = providers.value[provider.value]?.[0] ?? ''
  await loadChats()
  if (chats.value[0]) await select(chats.value[0])
})
onBeforeUnmount(() => { closeStream(); clearInterval(tick); window.removeEventListener('keydown', onEsc); small.removeEventListener('change', onSmall) })
</script>

<template>
  <section class="chat" :class="{ thc: layout.threadsCollapsed, thopen }">
    <div class="thscrim" @click="thopen = false" />
    <aside id="threads" ref="listEl" class="threads" :role="thopen ? 'dialog' : undefined" :aria-modal="thopen ? 'true' : undefined" aria-label="Chats">
      <div class="thbar">
        <span class="ttl">Chats</span>
        <button class="iconbtn thclose" aria-label="Close chat list" title="Close chat list" @click="thopen = false"><Icon name="close" /></button>
        <button class="iconbtn tg thtg" :aria-expanded="!layout.threadsCollapsed" aria-controls="threads"
                :title="layout.threadsCollapsed ? 'Expand chat list (Ctrl+Shift+B)' : 'Collapse chat list (Ctrl+Shift+B)'"
                :aria-label="layout.threadsCollapsed ? 'Expand chat list' : 'Collapse chat list'" @click="toggleThreads">
          <Icon :name="layout.threadsCollapsed ? 'expand' : 'collapse'" /></button>
      </div>
      <div class="rail">
        <button class="iconbtn newc" title="New chat" aria-label="New chat" @click="setThreadsCollapsed(false)"><Icon name="plus" /></button>
        <span class="sepr" />
        <button v-for="c in chats" :key="c.id" class="rt" :title="`${c.title} — ${subOf(c)}`" :aria-label="c.title"
                :aria-current="current?.id === c.id ? 'true' : undefined" @click="select(c)"><span class="dot" :class="dotOf(c.last_run_status)" /></button>
      </div>
      <div class="top">
        <div class="sel">
          <select v-model="provider" class="field" aria-label="Provider" @change="model = providers[provider]?.[0] ?? ''">
            <option v-for="(_, p) in providers" :key="p" :value="p">{{ pname(p) }}</option></select>
          <select v-model="model" class="field" aria-label="Model"><option v-for="m in providers[provider] ?? []" :key="m">{{ m }}</option></select>
        </div>
        <button class="btn primary" :disabled="creatingChat" @click="newChat"><span v-if="creatingChat" class="spinner" /><Icon v-else name="plus" />New chat</button>
      </div>
      <div class="tlist">
        <template v-for="[label, list] in groups" :key="label">
          <div class="tgroup">{{ label }}</div>
          <div v-for="c in list" :key="c.id" class="trow">
            <button class="thread" :aria-current="current?.id === c.id ? 'true' : undefined" @click="select(c)">
              <b>{{ c.title }}</b><span class="dot" :class="dotOf(c.last_run_status)" /><small>{{ subOf(c) }}</small></button>
            <button class="iconbtn del" :aria-label="`Delete chat ${c.title}`" title="Delete chat" @click="confirmDel = c"><Icon name="trash" /></button>
          </div>
        </template>
        <p v-if="!chats.length" class="muted" style="padding:12px 8px;margin:0">No chats yet.</p>
      </div>
    </aside>

    <div class="conv">
      <div class="convhead">
        <button ref="openBtn" class="btn sm chatsbtn" aria-controls="threads" :aria-expanded="thopen" @click="thopen = true"><Icon name="chat" />Chats<span class="count">{{ chats.length }}</span></button>
        <h2>{{ current?.title ?? 'Chat' }}</h2>
        <template v-if="current">
          <span class="chip"><span class="k">Model</span>
            <select v-model="current.provider" class="plainsel" aria-label="Provider" @change="current.model = providers[current.provider]?.[0] ?? current.model; changeModel()">
              <option v-for="(_, p) in providers" :key="p" :value="p">{{ pname(p) }}</option></select>·
            <select v-model="current.model" class="plainsel mono" aria-label="Model" @change="changeModel"><option v-for="m in providers[current.provider] ?? []" :key="m">{{ m }}</option></select></span>
          <span v-if="activeRun" class="chip"><span class="k">Run</span> <span class="mono">#{{ activeRun }}</span></span>
          <button v-if="activeRun" class="btn sm danger" :disabled="cancelling" @click="cancel"><span v-if="cancelling" class="spinner" />Cancel run</button>
        </template>
      </div>

      <div v-if="!Object.keys(providers).length" class="notice"><div class="callout"><span><b>No provider is configured.</b> An admin must set an API key under Settings.</span></div></div>

      <div v-if="current" class="msgs">
        <template v-for="(it, i) in items" :key="i">
          <div v-if="it.kind === 'user'" class="u">{{ it.text }}</div>
          <div v-else-if="it.kind === 'assistant'" class="a"><div class="by"><span class="mk"><i /></span>Sage</div><p>{{ it.text }}</p></div>
          <article v-else class="run" aria-label="Workflow run">
            <div class="runhead">
              <span class="name">{{ it.name }}</span>
              <span v-if="it.system || it.input?.system_name" class="on">on <b>{{ it.system?.label ?? it.input.system_name }}</b><template v-if="it.system"> · {{ it.system.sid }} · client {{ it.system.client }}</template></span>
              <span class="sp" />
              <span v-if="it.status === 'waiting'" class="pill warn"><span class="pulse">Waiting</span></span>
              <StatusPill v-else :status="it.status" :label="it.status === 'running' ? 'Running' : undefined" />
            </div>
            <div class="runmeta">
              <div><small>Started</small><b>{{ hm(it.startedAt ?? (it.runId != null ? runInfo[it.runId]?.run.started_at : undefined), true) }}</b></div>
              <div><small>Elapsed</small><b>{{ dur(it.startedAt ?? (it.runId != null ? runInfo[it.runId]?.run.started_at : undefined), it.status === 'running' || it.status === 'waiting' ? null : it.endedAt ?? (it.runId != null ? runInfo[it.runId]?.run.ended_at : null)) }}</b></div>
              <div><small>Steps</small><b>{{ it.steps.length }}</b></div>
              <div><small>Tokens in / out</small><b>{{ tokens(it) }}</b></div>
            </div>
            <ol v-if="it.steps.length" class="steps">
              <li v-for="s in it.steps" :key="s.seq" class="step" :class="{ done: s.status === 'ok', wait: s.status === 'waiting', run: s.status === 'running', err: s.status === 'error' }">
                <span class="mark"><Icon v-if="s.status === 'ok'" name="check" /><Icon v-else-if="s.status === 'error'" name="alert" /><i v-else /></span>
                <span class="t">{{ s.task }}</span>
                <span class="r">{{ s.attempts ? `check ${s.attempts}` : stepMs(s.ms) }}</span>
                <span v-if="s.status === 'waiting'" class="d">The SAP job is still running.
                  <span class="waitbox"><span>Next check <b>{{ hm(resumeAt ?? (it.runId != null ? runInfo[it.runId]?.run.resume_at : null)) }}</b> {{ tz }}</span></span></span>
              </li>
            </ol>
            <p v-else-if="it.status === 'running'" class="d0 muted">Starting the workflow.</p>
            <div v-if="it.callId && (it.status === 'ok' || it.status === 'error')" class="rowx" style="padding:0 16px 10px"><a class="btn sm" :href="`api/tool-calls/${it.callId}/report.xlsx`" download>Download report (.xlsx)</a><span class="help">Input, result and status of this call.</span></div>
            <details class="io"><summary><Icon name="chev" />Input sent to the workflow</summary><pre>{{ JSON.stringify(it.input, null, 2) }}</pre></details>
            <details v-if="it.output" class="io"><summary><Icon name="chev" />{{ it.isError ? 'Error returned to the model' : 'Result returned to the model' }}</summary><pre>{{ it.output }}</pre></details>
          </article>
        </template>
      </div>
      <div v-else class="msgs"><p class="muted" style="margin:0">Choose a chat or start a new one.</p></div>

      <div v-if="current" class="composer">
        <form class="box" @submit.prevent="send">
          <textarea v-model="text" rows="2" aria-label="Message" :disabled="!!activeRun"
                    :placeholder="activeRun ? 'Message Sage. It can\'t take new requests while this run is active.' : 'Message Sage'" @keydown="onKey" />
          <ul v-if="pending.length" class="attached" aria-label="Attached files">
            <li v-for="f in pending" :key="f.id"><span><b>{{ f.filename }}</b> <span class="help">{{ summary(f) }}</span>
              <span v-if="f.errors?.length" class="help bad block">{{ f.errors[0] }}</span></span>
              <button type="button" class="btn sm ghost" :aria-label="`Remove ${f.filename}`" @click="pending = pending.filter(x => x.id !== f.id)">Remove</button></li>
          </ul>
          <div class="tools">
            <input ref="fileInput" type="file" accept=".xlsx" multiple hidden @change="onFiles">
            <button type="button" class="btn sm" :disabled="!!activeRun || uploading" @click="fileInput?.click()"><span v-if="uploading" class="spinner" />Attach Excel</button>
            <details class="tpl"><summary class="btn sm ghost">Templates</summary>
              <div class="menu"><a v-for="t in templates" :key="t[0]" :href="`api/templates/${t[0]}.xlsx`" download>{{ t[1] }}</a></div></details>
            <span class="sp" /><button class="btn primary sm" :disabled="!!activeRun || !text.trim()">Send</button></div>
        </form>
        <div class="hint">Sage can only run workflows that an admin has set up and enabled on a system that passes its health check. For role changes you can attach an Excel file or just describe the changes in the message.</div>
      </div>
    </div>

    <ConfirmModal :open="!!confirmDel" title="Delete this chat?" confirm-label="Delete chat"
      text="The chat disappears from your list. Its run records and the audit log are kept." @confirm="remove" @cancel="confirmDel = null" />
  </section>
</template>
