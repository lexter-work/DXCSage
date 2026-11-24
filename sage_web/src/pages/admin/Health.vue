<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { get, post } from '../../api'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

const m = ref<any>({ systems: [], workflows: [], cells: [] })
const load = async () => (m.value = await get('api/health/matrix'))
const cell = (w: string, s: number) => m.value.cells.find((c: any) => c.workflow === w && c.system_id === s)
async function recheck(system_id?: number) { try { await post('api/health/recheck', { system_id: system_id ?? null }); await load(); toast('Re-checked') } catch (e) { toast(e) } }

const count = (h: string) => m.value.cells.filter((c: any) => c.health === h).length
const blocking = computed(() => m.value.systems.filter((s: any) => m.value.cells.some((c: any) => c.system_id === s.id && c.health === 'fail')).map((s: any) => s.label))
const title = computed(() => {
  if (!m.value.cells.length) return 'No workflow is set up on any system yet'
  const b = blocking.value
  if (!b.length) return 'No system is blocking a workflow'
  return b.length === 1 ? `${b[0]} is the only system blocking a workflow` : `${b.slice(0, -1).join(', ')} and ${b[b.length - 1]} are blocking workflows`
})
const CELL: Record<string, [string, string]> = { pass: ['cellok', 'Pass'], warn: ['cellwarn', 'Warn'], fail: ['cellbad', 'Fail'], unknown: ['celloff', 'Not checked'] }
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="head"><div><h1>{{ title }}</h1><p>Health per system and workflow. Checks are read-only and never run a write function.</p></div><span class="sp" />
      <button class="btn primary" @click="recheck()">Re-check all</button></div>
    <div v-if="m.cells.length" class="summary">
      <div class="big">{{ count('pass') }}<span> / {{ m.cells.length }} setups pass</span></div>
      <div class="muted">{{ count('warn') }} warning{{ count('warn') === 1 ? '' : 's' }} · {{ count('fail') }} failure{{ count('fail') === 1 ? '' : 's' }}</div>
    </div>
    <div class="panel tablewrap"><table class="hm">
      <thead><tr><th>System</th><th v-for="w in m.workflows" :key="w" class="mono">{{ w }}</th><th /></tr></thead>
      <tbody>
        <tr v-for="s in m.systems" :key="s.id">
          <td><span class="mono">{{ s.label }}</span> <StatusPill :status="s.status" /></td>
          <td v-for="w in m.workflows" :key="w">
            <router-link v-if="cell(w, s.id)" :class="CELL[cell(w, s.id).health]?.[0] ?? 'celloff'" :to="`/admin/workflows/${w}/${s.id}`">{{ CELL[cell(w, s.id).health]?.[1] ?? 'Not checked' }}</router-link>
            <span v-else class="celloff">Not set up</span>
          </td>
          <td><button class="btn sm" @click="recheck(s.id)">Re-check</button></td>
        </tr>
        <tr v-if="!m.systems.length"><td :colspan="m.workflows.length + 2" class="muted">No systems registered yet.</td></tr>
      </tbody></table></div>
  </section>
</template>
