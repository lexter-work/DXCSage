<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ status: string | null | undefined }>()
const cls = computed(() => {
  const s = props.status ?? ''
  if (['pass', 'ok', 'enabled', 'active', 'done'].includes(s)) return 'ok'
  if (['warn', 'waiting', 'setup', 'running', 'inactive', 'unknown'].includes(s)) return 'warn'
  if (['fail', 'failed', 'blocked', 'error', 'disabled', 'cancelled'].includes(s)) return 'bad'
  return 'off'
})
</script>
<template><span class="pill" :class="cls">{{ status || 'not set up' }}</span></template>
