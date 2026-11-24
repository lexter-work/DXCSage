<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { get } from '../api'
import DataTable from '../components/DataTable.vue'

const rows = ref<any[]>([])
onMounted(async () => (rows.value = (await get<any[]>('api/usage/me')).map(r => ({ ...r, id: r.day }))))
const month = new Date().toISOString().slice(0, 7)
const monthTokens = computed(() => rows.value.filter(r => r.day.startsWith(month)).reduce((n, r) => n + r.tokens_in + r.tokens_out, 0))
const title = computed(() => !rows.value.length ? 'No usage yet' : monthTokens.value ? `You used ${monthTokens.value >= 1000 ? Math.round(monthTokens.value / 1000) + 'k' : monthTokens.value} tokens this month` : 'No usage this month')
const columns = [
  { key: 'day', label: 'Day', mono: true }, { key: 'requests', label: 'Requests', num: true },
  { key: 'tokens_in', label: 'Tokens in', num: true }, { key: 'tokens_out', label: 'Tokens out', num: true },
  { key: 'workflow_calls', label: 'Workflow calls', num: true }, { key: 'task_calls', label: 'Task calls', num: true },
]
</script>
<template>
  <section class="page">
    <div class="head"><div><h1>{{ title }}</h1><p>Usage counts only. There are no usage limits.</p></div></div>
    <DataTable :columns="columns" :rows="rows">
      <template v-for="c in columns.filter(c => c.num)" :key="c.key" #[c.key]="{ row }">{{ row[c.key].toLocaleString() }}</template>
    </DataTable>
  </section>
</template>
