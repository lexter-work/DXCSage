<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ status: string | null | undefined; label?: string }>()
const cls = computed(() => {
  const s = (props.status ?? '').toLowerCase()
  if (['pass', 'ok', 'enabled', 'active', 'done', 'set'].includes(s)) return 'ok'
  if (['warn', 'waiting', 'setup', 'running', 'inactive', 'unknown'].includes(s)) return 'warn'
  if (['fail', 'failed', 'blocked', 'error', 'disabled'].includes(s)) return 'bad'
  return 'off'
})
// Sentence case in the markup, never via CSS.
const text = computed(() => {
  const t = props.label ?? props.status ?? 'not set up'
  return t.charAt(0).toUpperCase() + t.slice(1)
})
</script>
<template><span class="pill" :class="cls">{{ text }}</span></template>
