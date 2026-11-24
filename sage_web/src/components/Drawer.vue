<script setup lang="ts">
defineProps<{ open: boolean; title: string }>()
defineEmits<{ close: [] }>()
</script>
<template>
  <Teleport to="body">
    <div v-if="open" class="sdrawer-bg" @click.self="$emit('close')">
      <div class="sdrawer" role="dialog" aria-modal="true" :aria-label="title">
        <header><h2>{{ title }}</h2><button class="btn ghost sm" @click="$emit('close')">Close</button></header>
        <div class="sbody"><slot /></div>
      </div>
    </div>
  </Teleport>
</template>
