<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { get } from '../../api'
import DataTable from '../../components/DataTable.vue'
import Drawer from '../../components/Drawer.vue'
import StatusPill from '../../components/StatusPill.vue'

const runs = ref<any[]>([]), status = ref(''), detail = ref<any | null>(null)
const load = async () => (runs.value = await get(`api/runs${status.value ? `?status=${status.value}` : ''}`))
async function open(r: any) { detail.value = await get(`api/runs/${r.id}/detail`) }
const when = (iso: string) => new Date(iso).toLocaleString([], { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="head"><div><h1>Runs</h1><p>Every request, including runs of deleted chats.</p></div><span class="sp" />
      <select v-model="status" class="field" aria-label="Status" @change="load"><option value="">All statuses</option>
        <option v-for="s in ['running', 'waiting', 'done', 'failed', 'cancelled']" :key="s">{{ s }}</option></select></div>
    <DataTable clickable :rows="runs" :columns="[{key:'id',label:'Run',num:true},{key:'username',label:'User'},{key:'title',label:'Chat'},{key:'model',label:'Model',mono:true},{key:'status',label:'Status'},{key:'tokens_in',label:'Tokens in',num:true},{key:'tokens_out',label:'Tokens out',num:true},{key:'started_at',label:'Started',mono:true}]" @select="open">
      <template #title="{ row }"><span :class="{ muted: row.chat_deleted }">{{ row.chat_deleted ? 'Chat deleted' : row.title }}</span></template>
      <template #status="{ row }"><StatusPill :status="row.status" :label="row.status === 'cancelled' ? 'Cancelled' : undefined" /></template>
      <template #tokens_in="{ row }">{{ row.tokens_in.toLocaleString() }}</template>
      <template #tokens_out="{ row }">{{ row.tokens_out.toLocaleString() }}</template>
      <template #started_at="{ row }">{{ when(row.started_at) }}</template>
    </DataTable>
    <Drawer :open="!!detail" :title="`Run ${detail?.run.id ?? ''}`" @close="detail = null">
      <template v-if="detail">
        <div v-if="detail.run.error" class="callout"><span><b>{{ detail.run.error }}</b></span></div>
        <div v-for="c in detail.tool_calls" :key="c.id" class="toolcard">
          <div class="rowx"><b class="mono">{{ c.workflow }}</b><StatusPill :status="c.status" /><span class="sp" /><a v-if="c.status === 'ok' || c.status === 'error'" class="btn sm" :href="`api/tool-calls/${c.id}/report.xlsx`" download>Report (.xlsx)</a></div>
          <pre>{{ c.input }}</pre>
          <div v-for="s in c.steps" :key="s.id" class="muted mono" style="margin-top:6px">{{ s.seq }} · {{ s.kind }} · {{ s.name }} · {{ s.status }}<span v-if="s.error"> · {{ s.error }}</span></div>
          <pre v-if="c.output">{{ c.output }}</pre>
        </div>
        <div v-if="!detail.tool_calls.length" class="muted">No workflow calls in this run.</div>
      </template>
      <template #footer><button class="btn" @click="detail = null">Close</button></template>
    </Drawer>
  </section>
</template>
