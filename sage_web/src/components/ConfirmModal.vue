<script setup lang="ts">
defineProps<{ open: boolean; title: string; text: string; confirmLabel: string }>()
defineEmits<{ confirm: []; cancel: [] }>()
</script>
<template>
  <Teleport to="body">
    <div v-if="open" class="modal-bg" @click.self="$emit('cancel')">
      <div class="modal" role="alertdialog" aria-modal="true">
        <h2 style="margin:0 0 8px;font-size:15px">{{ title }}</h2>
        <p class="muted" style="margin:0 0 16px">{{ text }}</p>
        <div class="row" style="justify-content:flex-end">
          <button class="btn" @click="$emit('cancel')">Cancel</button>
          <button class="btn danger" @click="$emit('confirm')">{{ confirmLabel }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
