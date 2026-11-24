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
    <div class="head"><div><h1>Workflows</h1><p>The model sees a workflow only after you set it up and enable it on a system.</p></div></div>
    <div v-for="w in workflows" :key="w.name" class="wf">
      <div>
        <h2>{{ w.name }}</h2>
        <div class="tags"><StatusPill :status="w.enabled ? 'enabled' : 'disabled'" /><span v-if="w.durable" class="pill off">Long-running</span></div>
        <p class="desc">{{ w.description }}</p>
        <button class="btn sm" :class="{ primary: !w.enabled }" @click="setState(w)">{{ w.enabled ? 'Disable workflow' : 'Enable workflow' }}</button>
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
  </section>
</template>
