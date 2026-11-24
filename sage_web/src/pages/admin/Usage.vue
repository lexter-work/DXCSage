<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { get } from '../../api'
import DataTable from '../../components/DataTable.vue'

const rows = ref<any[]>([])
onMounted(async () => (rows.value = (await get<any[]>('api/usage')).map(r => ({ ...r, id: `${r.user_id}-${r.day}` }))))
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>Usage (all users)</h1><p>Counts per user and day. There are no limits.</p></div></div>
    <DataTable :rows="rows" :columns="[{key:'username',label:'User'},{key:'day',label:'Day',mono:true},{key:'requests',label:'Requests',mono:true},{key:'tokens_in',label:'Tokens in',mono:true},{key:'tokens_out',label:'Tokens out',mono:true},{key:'workflow_calls',label:'Workflow calls',mono:true},{key:'task_calls',label:'Task calls',mono:true}]" />
  </section>
</template>
