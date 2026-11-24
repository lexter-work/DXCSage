<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { get } from '../../api'
import DataTable from '../../components/DataTable.vue'

const all = ref<any[]>([]), user = ref('')
onMounted(async () => (all.value = (await get<any[]>('api/usage')).map(r => ({ ...r, id: `${r.user_id}-${r.day}` }))))
const users = computed(() => [...new Set(all.value.map(r => r.username))])
const rows = computed(() => user.value ? all.value.filter(r => r.username === user.value) : all.value)
const sum = (k: string) => rows.value.reduce((n, r) => n + r[k], 0)
const days = computed(() => new Set(all.value.map(r => r.day)).size)
const title = computed(() => {
  if (!all.value.length) return 'No usage yet'
  const per = new Map<string, number>()
  for (const r of all.value) per.set(r.username, (per.get(r.username) ?? 0) + r.requests)
  const [top, n] = [...per.entries()].sort((a, b) => b[1] - a[1])[0]
  const total = [...per.values()].reduce((a, b) => a + b, 0)
  return users.value.length === 1 ? `${top} made all ${total} requests` : `${top} made ${n} of ${total} requests in the last ${days.value} day${days.value === 1 ? '' : 's'} on record`
})
const cols = [
  { key: 'username', label: 'User' }, { key: 'day', label: 'Day', mono: true }, { key: 'requests', label: 'Requests', num: true },
  { key: 'tokens_in', label: 'Tokens in', num: true }, { key: 'tokens_out', label: 'Tokens out', num: true },
  { key: 'workflow_calls', label: 'Workflow calls', num: true }, { key: 'task_calls', label: 'Task calls', num: true },
]
</script>
<template>
  <section class="page">
    <div class="head"><div><h1>{{ title }}</h1><p>Counts per user and day. There are no limits.</p></div><span class="sp" />
      <select v-model="user" class="field" aria-label="User"><option value="">All users</option><option v-for="u in users" :key="u">{{ u }}</option></select></div>
    <DataTable :rows="rows" :columns="cols">
      <template v-for="c in cols.filter(c => c.num)" :key="c.key" #[c.key]="{ row }">{{ row[c.key].toLocaleString() }}</template>
      <template v-if="rows.length" #foot>
        <tfoot><tr><td>Total</td><td /><td class="num">{{ sum('requests').toLocaleString() }}</td><td class="num">{{ sum('tokens_in').toLocaleString() }}</td>
          <td class="num">{{ sum('tokens_out').toLocaleString() }}</td><td class="num">{{ sum('workflow_calls').toLocaleString() }}</td><td class="num">{{ sum('task_calls').toLocaleString() }}</td></tr></tfoot>
      </template>
    </DataTable>
  </section>
</template>
