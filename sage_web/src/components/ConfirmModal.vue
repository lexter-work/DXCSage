<script setup lang="ts">
defineProps<{ open: boolean; title: string; text: string; confirmLabel: string }>()
defineEmits<{ confirm: []; cancel: [] }>()
</script>
<template>
  <Teleport to="body">
    <div v-if="open" class="modal-bg" @click.self="$emit('cancel')" @keydown.esc="$emit('cancel')">
      <div class="modal" role="alertdialog" aria-modal="true" :aria-label="title">
        <h2>{{ title }}</h2>
        <p>{{ text }}</p>
        <div class="actions">
          <button class="btn" @click="$emit('cancel')">Cancel</button>
          <button class="btn danger" @click="$emit('confirm')">{{ confirmLabel }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
