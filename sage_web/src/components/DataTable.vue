<script setup lang="ts">
defineProps<{ columns: { key: string; label: string; mono?: boolean }[]; rows: any[]; clickable?: boolean }>()
defineEmits<{ select: [row: any] }>()
</script>
<template>
  <div class="card"><div class="tablewrap"><table>
    <thead><tr><th v-for="c in columns" :key="c.key">{{ c.label }}</th></tr></thead>
    <tbody>
      <tr v-for="(r, i) in rows" :key="r.id ?? i" :class="{ click: clickable }" @click="clickable && $emit('select', r)">
        <td v-for="c in columns" :key="c.key" :class="{ mono: c.mono }"><slot :name="c.key" :row="r">{{ r[c.key] }}</slot></td>
      </tr>
      <tr v-if="!rows.length"><td :colspan="columns.length" class="muted">Nothing here yet.</td></tr>
    </tbody>
  </table></div></div>
</template>
