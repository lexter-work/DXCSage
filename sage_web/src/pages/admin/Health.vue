<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { get, post } from '../../api'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

const m = ref<any>({ systems: [], workflows: [], cells: [] })
const load = async () => (m.value = await get('api/health/matrix'))
const cell = (w: string, s: number) => m.value.cells.find((c: any) => c.workflow === w && c.system_id === s)
async function recheck(system_id?: number) { try { await post('api/health/recheck', { system_id: system_id ?? null }); await load(); toast('Re-checked') } catch (e) { toast(e) } }
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>Health</h1><p>Per system and workflow. Checks are read-only and never run a write function.</p></div><span class="spacer" />
      <button class="btn primary" @click="recheck()">Re-check all</button></div>
    <div class="card"><div class="tablewrap"><table class="matrix">
      <thead><tr><th style="text-align:left">System</th><th v-for="w in m.workflows" :key="w" class="mono">{{ w }}</th><th></th></tr></thead>
      <tbody>
        <tr v-for="s in m.systems" :key="s.id"><td style="text-align:left" class="mono">{{ s.label }} <StatusPill :status="s.status" /></td>
          <td v-for="w in m.workflows" :key="w">
            <router-link v-if="cell(w, s.id)" :to="`/admin/workflows/${w}/${s.id}`"><StatusPill :status="cell(w, s.id).health" /></router-link>
            <span v-else class="muted">not set up</span></td>
          <td><button class="btn sm" @click="recheck(s.id)">Re-check</button></td></tr>
        <tr v-if="!m.systems.length"><td :colspan="m.workflows.length + 2" class="muted">No systems registered yet.</td></tr>
      </tbody></table></div></div>
  </section>
</template>
