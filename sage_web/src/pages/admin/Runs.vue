<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { get } from '../../api'
import DataTable from '../../components/DataTable.vue'
import Drawer from '../../components/Drawer.vue'
import StatusPill from '../../components/StatusPill.vue'

const runs = ref<any[]>([]), status = ref(''), detail = ref<any | null>(null)
const load = async () => (runs.value = await get(`api/runs${status.value ? `?status=${status.value}` : ''}`))
async function open(r: any) { detail.value = await get(`api/runs/${r.id}/detail`) }
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>Runs</h1><p>Every request, including runs of deleted chats.</p></div><span class="spacer" />
      <select class="field" style="width:auto" v-model="status" @change="load"><option value="">All statuses</option>
        <option v-for="s in ['running','waiting','done','failed','cancelled']" :key="s">{{ s }}</option></select></div>
    <DataTable clickable :rows="runs" @select="open" :columns="[{key:'id',label:'Run',mono:true},{key:'username',label:'User'},{key:'title',label:'Chat'},{key:'model',label:'Model',mono:true},{key:'status',label:'Status'},{key:'tokens_in',label:'Tokens in',mono:true},{key:'tokens_out',label:'Tokens out',mono:true},{key:'started_at',label:'Started',mono:true}]">
      <template #status="{ row }"><StatusPill :status="row.status" /><span v-if="row.chat_deleted" class="muted"> · chat deleted</span></template>
    </DataTable>
    <Drawer :open="!!detail" :title="`Run ${detail?.run.id ?? ''}`" @close="detail = null">
      <template v-if="detail">
        <div v-if="detail.run.error" class="callout"><b>{{ detail.run.error }}</b></div>
        <div v-for="c in detail.tool_calls" :key="c.id" class="toolcard">
          <b class="mono">{{ c.workflow }}</b> <StatusPill :status="c.status" />
          <pre>{{ c.input }}</pre>
          <div v-for="s in c.steps" :key="s.id" class="muted mono" style="margin-top:6px">{{ s.seq }} · {{ s.kind }} · {{ s.name }} · {{ s.status }}<span v-if="s.error"> · {{ s.error }}</span></div>
          <pre v-if="c.output">{{ c.output }}</pre>
        </div>
        <div v-if="!detail.tool_calls.length" class="muted">No workflow calls in this run.</div>
      </template>
    </Drawer>
  </section>
</template>
