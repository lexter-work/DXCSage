<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { get, put } from '../../api'
import Drawer from '../../components/Drawer.vue'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

const router = useRouter()
const workflows = ref<any[]>([]), systems = ref<any[]>([]), pick = ref<Record<string, number>>({})
async function load() { workflows.value = await get('api/workflows'); systems.value = (await get<any[]>('api/systems')).filter(s => s.status === 'active') }
async function setState(w: any) { try { await put(`api/workflows/${w.name}/state`, { enabled: !w.enabled }); await load() } catch (e) { toast(e) } }
async function setUp(w: any) {
  const id = pick.value[w.name]
  if (!id) return toast('Choose a system first.')
  try { await put(`api/workflows/${w.name}/systems/${id}`, { settings: {} }); router.push(`/admin/workflows/${w.name}/${id}`) } catch (e) { toast(e) }
}
// Email notifications: which groups get an email on which state of the workflow.
const nf = ref<any | null>(null), allGroups = ref<any[]>([])
async function openNotif(w: any) {
  try {
    const r = await get(`api/workflows/${w.name}/notifications`)
    allGroups.value = await get('api/email/groups')
    const sel: Record<number, { events: string[]; mode: string }> = {}
    for (const x of r.rules) sel[x.group_id] = { events: [...x.events], mode: x.mode }
    nf.value = { name: w.name, events: r.events, sel }
  } catch (e) { toast(e) }
}
function toggleGroup(gid: number) { const s = nf.value.sel; if (s[gid]) delete s[gid]; else s[gid] = { events: ['completed', 'failed'], mode: 'instant' } }
function toggleEvent(gid: number, key: string) { const a: string[] = nf.value.sel[gid].events; const i = a.indexOf(key); if (i < 0) a.push(key); else a.splice(i, 1) }
async function saveNotif() {
  const rules = Object.entries(nf.value.sel as Record<string, { events: string[]; mode: string }>).map(([g, v]) => ({ group_id: Number(g), events: v.events, mode: v.mode }))
  try { await put(`api/workflows/${nf.value.name}/notifications`, { rules }); toast('Email notifications saved'); nf.value = null } catch (e) { toast(e) }
}
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="head"><div><h1>Workflows</h1><p>The model sees a workflow only after you set it up and enable it on a system.</p></div></div>
    <div v-for="w in workflows" :key="w.name" class="wf">
      <div>
        <h2>{{ w.name }}</h2>
        <div class="tags"><StatusPill :status="w.enabled ? 'enabled' : 'disabled'" /><span v-if="w.durable" class="pill off">Long-running</span></div>
        <p class="desc">{{ w.description }}</p>
        <div class="rowx"><button class="btn sm" :class="{ primary: !w.enabled }" @click="setState(w)">{{ w.enabled ? 'Disable workflow' : 'Enable workflow' }}</button>
          <button class="btn sm ghost" @click="openNotif(w)">Email notifications</button></div>
      </div>
      <div>
        <div v-if="w.bindings.length" class="panel tablewrap"><table>
          <thead><tr><th>System</th><th>Setup</th><th>Last health check</th><th /></tr></thead>
          <tbody>
            <tr v-for="b in w.bindings" :key="b.system_id">
              <td class="mono">{{ b.label }} ({{ b.sid }})</td><td><StatusPill :status="b.status" /></td>
              <td><StatusPill :status="b.health" :label="b.health === 'unknown' ? 'Not checked' : undefined" /></td>
              <td><router-link class="btn sm" :to="`/admin/workflows/${w.name}/${b.system_id}`">Open setup guide</router-link></td>
            </tr>
          </tbody></table></div>
        <div v-else class="panel"><div class="muted" style="padding:18px">Not set up on any system.</div></div>
        <div class="setup">
          <select v-model="pick[w.name]" class="field" :aria-label="`System for ${w.name}`"><option :value="undefined" disabled>Choose a system</option>
            <option v-for="s in systems" :key="s.id" :value="s.id">{{ s.label }} ({{ s.sid }})</option></select>
          <button class="btn primary" @click="setUp(w)">Set up on this system</button>
        </div>
      </div>
    </div>
    <p v-if="!workflows.length" class="muted">No workflows are installed.</p>

    <Drawer :open="!!nf" :title="nf ? `Email notifications: ${nf.name}` : ''" mono @close="nf = null">
      <template v-if="nf">
        <div class="callout info"><span>Tag the groups that get an email when this workflow changes state, and choose which states. Groups are made on the <router-link to="/admin/email">Email groups</router-link> page. Emails state the system, who asked and the state, never results.</span></div>
        <p v-if="!allGroups.length" class="muted">No email group exists yet.</p>
        <div class="notif">
          <div v-for="g in allGroups" :key="g.id" class="row">
            <label class="chk"><input type="checkbox" :checked="!!nf.sel[g.id]" @change="toggleGroup(g.id)"> <b>{{ g.name }}</b> <span class="help">{{ g.members }} {{ g.members === 1 ? 'person' : 'people' }}</span></label>
            <div v-if="nf.sel[g.id]" class="evs">
              <label v-for="e in nf.events" :key="e.key" class="chk"><input type="checkbox" :checked="nf.sel[g.id].events.includes(e.key)" @change="toggleEvent(g.id, e.key)"> {{ e.label }}</label>
              <label class="lbl" style="flex-basis:100%">Send<select v-model="nf.sel[g.id].mode" class="field"><option value="instant">Immediately</option><option value="hourly">As an hourly digest</option><option value="daily">As a daily digest</option></select></label>
            </div>
          </div>
        </div>
      </template>
      <template #footer><button class="btn" @click="nf = null">Cancel</button><button class="btn primary" @click="saveNotif">Save</button></template>
    </Drawer>
  </section>
</template>
