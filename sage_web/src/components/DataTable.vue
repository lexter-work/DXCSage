<script setup lang="ts">
defineProps<{ columns: { key: string; label: string; mono?: boolean; num?: boolean }[]; rows: any[]; clickable?: boolean }>()
defineEmits<{ select: [row: any] }>()
</script>
<template>
  <div class="panel tablewrap"><table>
    <thead><tr><th v-for="c in columns" :key="c.key" :class="{ num: c.num }">{{ c.label }}</th></tr></thead>
    <tbody>
      <tr v-for="(r, i) in rows" :key="r.id ?? i" :class="{ click: clickable }" :tabindex="clickable ? 0 : undefined"
          @click="clickable && $emit('select', r)" @keydown.enter="clickable && $emit('select', r)">
        <td v-for="c in columns" :key="c.key" :class="{ mono: c.mono, num: c.num }"><slot :name="c.key" :row="r">{{ r[c.key] }}</slot></td>
      </tr>
      <tr v-if="!rows.length"><td :colspan="columns.length" class="muted">Nothing here yet.</td></tr>
    </tbody>
    <slot name="foot" />
  </table></div>
</template>
