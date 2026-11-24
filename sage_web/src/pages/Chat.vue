<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { del, get, patch, post } from '../api'
import { applyEvent, buildItems, type Item, type Msg } from '../messages'
import ConfirmModal from '../components/ConfirmModal.vue'
import StatusPill from '../components/StatusPill.vue'
import { toast } from '../toast'

const chats = ref<any[]>([]), current = ref<any | null>(null), items = ref<Item[]>([])
const providers = ref<Record<string, string[]>>({}), provider = ref(''), model = ref('')
const text = ref(''), activeRun = ref<number | null>(null), resumeAt = ref<string | null>(null)
const confirmDel = ref<any | null>(null)
let es: EventSource | null = null, lastEvent = 0, retry: number | undefined, messages: Msg[] = []

async function loadChats() { chats.value = await get('api/chats') }
async function loadMessages() {
  if (!current.value) return
  messages = await get(`api/chats/${current.value.id}/messages`)
  items.value = buildItems(messages, activeRun.value)
}
function closeStream() { es?.close(); es = null; clearTimeout(retry) }

function attach(runId: number, after = 0) {
  closeStream()
  activeRun.value = runId; lastEvent = after
  if (after === 0) items.value = buildItems(messages, runId)
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
  }
  // EventSource reconnects with Last-Event-ID, not our ?after=, so reopen by hand.
  es.onerror = () => { if (activeRun.value === runId) { es?.close(); retry = window.setTimeout(() => attach(runId, lastEvent), 1000) } }
}

async function select(c: any) {
  closeStream(); activeRun.value = null; current.value = c
  await loadMessages()
  if (['running', 'waiting'].includes(c.last_run_status)) attach(c.last_run_id)
}
async function newChat() {
  if (!provider.value || !model.value) return toast('Choose a provider and model first.')
  try {
    const { id } = await post('api/chats', { provider: provider.value, model: model.value })
    await loadChats(); await select(chats.value.find(c => c.id === id))
  } catch (e) { toast(e) }
}
async function changeModel() {
  if (!current.value) return
  try { await patch(`api/chats/${current.value.id}`, { provider: current.value.provider, model: current.value.model }) } catch (e) { toast(e) }
}
async function send() {
  if (!current.value || !text.value.trim() || activeRun.value) return
  const t = text.value; text.value = ''
  try {
    const { run_id } = await post(`api/chats/${current.value.id}/runs`, { text: t })
    messages = await get(`api/chats/${current.value.id}/messages`)
    attach(run_id)
  } catch (e) { text.value = t; toast(e) }
}
async function cancel() { if (activeRun.value) await post(`api/runs/${activeRun.value}/cancel`).catch(toast) }
async function remove() {
  const c = confirmDel.value; confirmDel.value = null
  await del(`api/chats/${c.id}`).catch(toast)
  if (current.value?.id === c.id) { current.value = null; items.value = []; closeStream(); activeRun.value = null }
  await loadChats()
}

onMounted(async () => {
  providers.value = await get('api/providers')
  provider.value = Object.keys(providers.value)[0] ?? ''
  model.value = providers.value[provider.value]?.[0] ?? ''
  await loadChats()
  if (chats.value[0]) await select(chats.value[0])
})
onBeforeUnmount(closeStream)
</script>

<template>
  <section class="page">
    <div class="page-head"><div><h1>Chat</h1><p>Ask for SAP work. Workflows run on the systems an admin has set up.</p></div></div>
    <div v-if="!Object.keys(providers).length" class="callout"><b>No provider is configured.</b><span>An admin must set an API key under Settings.</span></div>
    <div class="chat-wrap">
      <div class="card"><div class="card-b chat-list">
        <div class="row">
          <select class="field" style="width:auto" v-model="provider" @change="model = providers[provider]?.[0] ?? ''"><option v-for="(_, p) in providers" :key="p">{{ p }}</option></select>
          <select class="field" style="width:auto" v-model="model"><option v-for="m in providers[provider] ?? []" :key="m">{{ m }}</option></select>
          <button class="btn primary" @click="newChat">New chat</button>
        </div>
        <div v-for="c in chats" :key="c.id" class="row">
          <button :class="{ sel: current?.id === c.id }" style="flex:1" @click="select(c)">{{ c.title }}</button>
          <button class="btn ghost sm" :aria-label="`Delete chat ${c.title}`" @click="confirmDel = c">Delete</button>
        </div>
      </div></div>

      <div class="chat-main" v-if="current">
        <div class="row">
          <select class="field" style="width:auto" v-model="current.provider" @change="current.model = providers[current.provider]?.[0] ?? current.model; changeModel()">
            <option v-for="(_, p) in providers" :key="p">{{ p }}</option></select>
          <select class="field" style="width:auto" v-model="current.model" @change="changeModel"><option v-for="m in providers[current.provider] ?? []" :key="m">{{ m }}</option></select>
          <StatusPill v-if="activeRun" :status="resumeAt ? 'waiting' : 'running'" />
          <span v-if="resumeAt" class="muted mono">next check {{ resumeAt }}</span>
          <button v-if="activeRun" class="btn sm danger" @click="cancel">Cancel run</button>
        </div>
        <div class="msgs">
          <template v-for="(it, i) in items" :key="i">
            <div v-if="it.kind === 'user'" class="bubble user">{{ it.text }}</div>
            <div v-else-if="it.kind === 'assistant'" class="bubble assistant">{{ it.text }}</div>
            <details v-else class="toolcard" :open="it.status === 'running' || it.status === 'waiting'">
              <summary><b class="mono">{{ it.name }}</b> <StatusPill :status="it.status" /></summary>
              <pre>{{ JSON.stringify(it.input, null, 2) }}</pre>
              <div v-for="s in it.steps" :key="s.seq" class="muted mono" style="margin-top:4px">{{ s.seq }} · {{ s.task }} · {{ s.status }}</div>
              <pre v-if="it.output">{{ it.output }}</pre>
            </details>
          </template>
        </div>
        <form class="row" @submit.prevent="send">
          <input class="field" style="flex:1" v-model="text" :disabled="!!activeRun" placeholder="Message DXC Sage" aria-label="Message">
          <button class="btn primary" :disabled="!!activeRun || !text.trim()">Send</button>
        </form>
      </div>
      <div v-else class="muted">Choose a chat or start a new one.</div>
    </div>
    <ConfirmModal :open="!!confirmDel" title="Delete this chat?" confirm-label="Delete chat"
      text="The chat disappears from your list. Its run records and the audit log are kept." @confirm="remove" @cancel="confirmDel = null" />
  </section>
</template>
