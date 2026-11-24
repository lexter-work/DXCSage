<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { get, put } from '../../api'
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
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>Workflows</h1><p>The model sees a workflow only after you set it up and enable it on a system.</p></div></div>
    <div v-for="w in workflows" :key="w.name" class="card" style="margin-bottom:14px">
      <div class="card-h"><h2 class="mono">{{ w.name }}</h2><StatusPill :status="w.enabled ? 'enabled' : 'disabled'" />
        <span v-if="w.durable" class="pill off">long-running</span><span class="spacer" />
        <button class="btn sm" @click="setState(w)">{{ w.enabled ? 'Disable workflow' : 'Enable workflow' }}</button></div>
      <div class="card-b" style="display:grid;gap:10px">
        <p class="muted" style="margin:0">{{ w.description }}</p>
        <table><thead><tr><th>System</th><th>Setup</th><th>Last health check</th><th></th></tr></thead><tbody>
          <tr v-for="b in w.bindings" :key="b.system_id"><td class="mono">{{ b.label }} ({{ b.sid }})</td><td><StatusPill :status="b.status" /></td>
            <td><StatusPill :status="b.health" /></td>
            <td><router-link class="btn sm" :to="`/admin/workflows/${w.name}/${b.system_id}`">Open setup guide</router-link></td></tr>
          <tr v-if="!w.bindings.length"><td colspan="4" class="muted">Not set up on any system.</td></tr></tbody></table>
        <div class="row"><select class="field" style="width:auto" v-model="pick[w.name]"><option :value="undefined" disabled>Choose a system</option>
          <option v-for="s in systems" :key="s.id" :value="s.id">{{ s.label }} ({{ s.sid }})</option></select>
          <button class="btn primary" @click="setUp(w)">Set up on this system</button></div>
      </div>
    </div>
  </section>
</template>
