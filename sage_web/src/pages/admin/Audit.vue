<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { get, post } from '../../api'
import DataTable from '../../components/DataTable.vue'
import Icon from '../../components/Icon.vue'
import { toast } from '../../toast'

// The event names sage_api writes (offered as suggestions in the filter).
const EVENTS = ['auth.bootstrap', 'auth.fail', 'auth.login', 'auth.password_change', 'chat.create', 'chat.delete', 'config.change', 'run.cancel', 'run.end',
  'run.start', 'system.create', 'system.credentials', 'system.disable', 'system.health_check', 'system.update', 'tool.call', 'tool.end', 'tool.step',
  'workflow.disable', 'workflow.enable', 'workflow.setup']
const rows = ref<any[]>([]), event = ref(''), actor = ref(''), verified = ref<string | null>(null)
const latest = computed(() => rows.value[0]?.id ?? 0)
async function load() {
  const q = new URLSearchParams(); if (event.value) q.set('event', event.value); if (actor.value) q.set('actor', actor.value)
  rows.value = await get(`api/audit?${q}`)
}
async function verify() {
  const r = await post('api/audit/verify')
  verified.value = r.ok ? `Audit chain verified. No tampering found in ${latest.value.toLocaleString()} entries.` : `The chain is broken at entry ${r.bad_id}.`
  if (!r.ok) toast(verified.value)
}
const fam = (e: string) => e.split('.')[0] + '.'
const act = (e: string) => e.split('.').slice(1).join('.')
const when = (ts: string) => new Date(ts).toLocaleString([], { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="head"><div><h1>Audit log</h1><p>Append-only and hash-chained. Every request, task and admin action is here.</p></div><span class="sp" />
      <button class="btn" @click="verify">Verify chain</button><a class="btn" href="api/audit/export.csv" download>Export CSV</a></div>
    <div v-if="verified && verified.startsWith('Audit chain verified')" class="ok-line"><Icon name="check" />{{ verified }}</div>
    <div class="filters">
      <input v-model="event" class="field mono" list="evlist" placeholder="Event, e.g. tool.step" aria-label="Event" @keyup.enter="load">
      <datalist id="evlist"><option v-for="e in EVENTS" :key="e" :value="e" /></datalist>
      <input v-model="actor" class="field" placeholder="Actor" aria-label="Actor" style="width:180px" @keyup.enter="load"><button class="btn" @click="load">Filter</button>
      <span class="sp" /><span class="muted" style="font-size:12.5px">Showing the latest {{ rows.length }} of {{ latest.toLocaleString() }}</span>
    </div>
    <DataTable :rows="rows" :columns="[{key:'id',label:'#',num:true},{key:'ts',label:'Time',mono:true},{key:'event',label:'Event'},{key:'actor',label:'Actor'},{key:'run_id',label:'Run',num:true},{key:'detail',label:'Detail'}]">
      <template #id="{ row }">{{ row.id.toLocaleString() }}</template>
      <template #ts="{ row }">{{ when(row.ts) }}</template>
      <template #event="{ row }"><span class="ev" :class="{ warn: row.event === 'auth.fail' }"><span>{{ fam(row.event) }}</span><b>{{ act(row.event) }}</b></span></template>
      <template #run_id="{ row }">{{ row.run_id ?? '—' }}</template>
      <template #detail="{ row }"><span class="wrapcell">{{ row.detail.length > 160 ? row.detail.slice(0, 160) + '…' : row.detail }}</span></template>
    </DataTable>
  </section>
</template>
