<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { del, get, post, put } from '../../api'
import DataTable from '../../components/DataTable.vue'
import Drawer from '../../components/Drawer.vue'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

const schedules = ref<any[]>([]), workflows = ref<any[]>([])
type Form = { id: number | null; name: string; workflow: string; system: string; extra: Record<string, string>; kind: 'interval' | 'daily'; interval: number; at: string; enabled: boolean }
const sel = ref<Form | null>(null)

const choices = computed(() => workflows.value.filter(w => w.schedulable))
const wf = computed(() => choices.value.find(w => w.name === sel.value?.workflow))
const systems = computed(() => (wf.value?.bindings ?? []).filter((b: any) => b.status === 'enabled'))

async function load() { schedules.value = await get('api/schedules'); workflows.value = await get('api/workflows') }
function blank(): Form { return { id: null, name: '', workflow: choices.value[0]?.name ?? '', system: '', extra: {}, kind: 'interval', interval: 60, at: '06:00', enabled: true } }
function create() { sel.value = blank(); pickDefaults() }
function pickDefaults() { if (sel.value && !systems.value.some((b: any) => b.label === sel.value!.system)) sel.value.system = systems.value[0]?.label ?? '' }
function edit(s: any) {
  const { system_name, ...rest } = s.input
  sel.value = { id: s.id, name: s.name, workflow: s.workflow, system: system_name ?? '', kind: s.kind, interval: s.interval_minutes ?? 60, at: s.at_time ?? '06:00', enabled: s.enabled,
    extra: Object.fromEntries(Object.entries(rest).map(([k, v]) => [k, Array.isArray(v) ? v.join(', ') : String(v ?? '')])) }
}
function input(): Record<string, unknown> {
  const out: Record<string, unknown> = { system_name: sel.value!.system }
  for (const f of wf.value?.input_fields ?? []) {
    const v = (sel.value!.extra[f.name] ?? '').trim()
    if (v) out[f.name] = f.list ? v.split(',').map(x => x.trim()).filter(Boolean) : v
  }
  return out
}
async function save() {
  const f = sel.value!
  const body = { name: f.name, workflow: f.workflow, input: input(), kind: f.kind, enabled: f.enabled,
    interval_minutes: f.kind === 'interval' ? Number(f.interval) : null, at_time: f.kind === 'daily' ? f.at : null }
  try { f.id ? await put(`api/schedules/${f.id}`, body) : await post('api/schedules', body); toast('Schedule saved'); sel.value = null; await load() } catch (e) { toast(e) }
}
async function toggle(s: any) { try { await post(`api/schedules/${s.id}/enabled`, { enabled: !s.enabled }); await load() } catch (e) { toast(e) } }
async function runNow(s: any) { try { await post(`api/schedules/${s.id}/run`); toast('Run started'); await load() } catch (e) { toast(e) } }
async function remove() { try { await del(`api/schedules/${sel.value!.id}`); toast('Schedule deleted. Its past runs stay on the Runs page.'); sel.value = null; await load() } catch (e) { toast(e) } }
const when = (s: any) => (s.kind === 'interval' ? (s.interval_minutes % 1440 === 0 ? `Every ${s.interval_minutes / 1440} day(s)` : s.interval_minutes % 60 === 0 ? `Every ${s.interval_minutes / 60} hour(s)` : `Every ${s.interval_minutes} min`) : `Daily at ${s.at_time} UTC`)
const rows = computed(() => schedules.value.map(s => ({ ...s, when: when(s), target: `${s.workflow} on ${s.input.system_name ?? '-'}`, state: s.enabled ? (s.last_run_status ?? 'waiting') : 'disabled' })))
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="head"><div><h1>Schedules</h1><p>Run a read-only workflow again and again, without a chat. Combine it with email groups to be told when a state changes, for example SUM going to ERROR.</p></div>
      <span class="sp" /><button class="btn primary" :disabled="!choices.length" @click="create">New schedule</button></div>
    <div class="callout info"><span>Times are in UTC. A schedule runs as an admin account with the same checks as a chat run. Only read-only workflows can be scheduled. If a run is still going when the next one is due, that one is skipped. After the server was off, a missed run happens once.</span></div>

    <DataTable clickable :rows="rows" :columns="[{key:'name',label:'Name'},{key:'target',label:'Workflow',mono:true},{key:'when',label:'When'},{key:'next_run_at',label:'Next run',mono:true},{key:'last_run_at',label:'Last run',mono:true},{key:'state',label:'Last result'}]" @select="edit">
      <template #state="{ row }"><StatusPill :status="row.state === 'done' ? 'ok' : row.state === 'failed' ? 'fail' : row.state === 'disabled' ? 'off' : 'warn'" :label="row.state === 'waiting' && !row.last_run_id ? 'Not run yet' : row.state" /></template>
    </DataTable>
    <p v-if="!schedules.length" class="muted">No schedule yet.</p>

    <Drawer :open="!!sel" :title="sel?.id ? sel.name : 'New schedule'" @close="sel = null">
      <template v-if="sel">
        <label class="lbl">Name<input v-model="sel.name" class="field" maxlength="60"></label>
        <label class="lbl">Workflow<select v-model="sel.workflow" class="field" @change="sel.extra = {}; pickDefaults()"><option v-for="w in choices" :key="w.name" :value="w.name">{{ w.name }}</option></select></label>
        <p v-if="wf" class="help" style="margin:0">{{ wf.description }}</p>
        <label class="lbl">System<select v-model="sel.system" class="field"><option v-for="b in systems" :key="b.system_id" :value="b.label">{{ b.label }} ({{ b.sid }})</option></select></label>
        <p v-if="!systems.length" class="help bad" role="alert">This workflow is not enabled on any system. Set it up on the Workflows page first.</p>
        <label v-for="f in wf?.input_fields ?? []" :key="f.name" class="lbl">{{ f.label }}<span v-if="!f.required" class="help"> (optional)</span><span v-if="f.list" class="help"> (comma separated)</span>
          <input v-model="sel.extra[f.name]" class="field mono" autocomplete="off"></label>
        <h3>When</h3>
        <div class="sched-when">
          <label class="lbl">Repeat<select v-model="sel.kind" class="field"><option value="interval">Every N minutes</option><option value="daily">Every day at a time</option></select></label>
          <label v-if="sel.kind === 'interval'" class="lbl">Minutes (5 to 10080)<input v-model="sel.interval" class="field mono" inputmode="numeric"></label>
          <label v-else class="lbl">Time (UTC)<input v-model="sel.at" class="field mono" type="time"></label>
        </div>
        <label class="chk"><input v-model="sel.enabled" type="checkbox"> Enabled</label>
        <div v-if="sel.id" class="rowx"><button class="btn sm" @click="runNow(schedules.find(s => s.id === sel!.id))">Run now</button>
          <button class="btn sm" @click="toggle(schedules.find(s => s.id === sel!.id)); sel = null">{{ sel.enabled ? 'Disable' : 'Enable' }}</button></div>
      </template>
      <template #footer><button v-if="sel?.id" class="btn danger" @click="remove">Delete</button><span class="sp" />
        <button class="btn" @click="sel = null">Cancel</button><button class="btn primary" :disabled="!sel?.name.trim() || !sel?.system" @click="save">Save</button></template>
    </Drawer>
  </section>
</template>
