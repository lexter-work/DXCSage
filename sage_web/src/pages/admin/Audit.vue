<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { get, post } from '../../api'
import DataTable from '../../components/DataTable.vue'
import { toast } from '../../toast'

const rows = ref<any[]>([]), event = ref(''), actor = ref('')
async function load() {
  const q = new URLSearchParams(); if (event.value) q.set('event', event.value); if (actor.value) q.set('actor', actor.value)
  rows.value = await get(`api/audit?${q}`)
}
async function verify() {
  const r = await post('api/audit/verify')
  toast(r.ok ? 'Audit chain verified. No tampering found.' : `Chain broken at entry ${r.bad_id}.`)
}
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>Audit log</h1><p>Append-only and hash-chained.</p></div><span class="spacer" />
      <button class="btn" @click="verify">Verify chain</button><a class="btn" href="api/audit/export.csv" download>Export CSV</a></div>
    <div class="row" style="margin-bottom:12px"><input class="field" style="width:220px" v-model="event" placeholder="Event, e.g. tool.step" @keyup.enter="load">
      <input class="field" style="width:200px" v-model="actor" placeholder="Actor" @keyup.enter="load"><button class="btn" @click="load">Filter</button></div>
    <DataTable :rows="rows" :columns="[{key:'id',label:'#',mono:true},{key:'ts',label:'Time',mono:true},{key:'event',label:'Event',mono:true},{key:'actor',label:'Actor'},{key:'run_id',label:'Run',mono:true},{key:'detail',label:'Detail',mono:true}]">
      <template #detail="{ row }"><span style="word-break:break-all">{{ row.detail.length > 140 ? row.detail.slice(0, 140) + '…' : row.detail }}</span></template>
    </DataTable>
  </section>
</template>
