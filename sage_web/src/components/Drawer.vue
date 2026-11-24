<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import Icon from './Icon.vue'

const props = defineProps<{ open: boolean; title: string; mono?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const panel = ref<HTMLElement | null>(null)
let opener: HTMLElement | null = null

function onKey(e: KeyboardEvent) { if (e.key === 'Escape') emit('close') }
watch(() => props.open, async (o) => {
  if (o) {
    opener = document.activeElement as HTMLElement | null
    window.addEventListener('keydown', onKey)
    await nextTick()
    const first = panel.value?.querySelector<HTMLElement>('.body input, .body select, .body textarea, .body button')
    ;(first ?? panel.value?.querySelector<HTMLElement>('header button'))?.focus()
  } else {
    window.removeEventListener('keydown', onKey)
    opener?.focus?.()
  }
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>
<template>
  <Teleport to="body">
    <div v-if="open" class="scrim on" @click.self="emit('close')">
      <div ref="panel" class="drawer" role="dialog" aria-modal="true" :aria-label="title">
        <header>
          <h2 :class="{ mono }">{{ title }}</h2>
          <slot name="status" />
          <button class="btn ghost sm" aria-label="Close" @click="emit('close')"><Icon name="close" /></button>
        </header>
        <div class="body"><slot /></div>
        <footer v-if="$slots.footer"><slot name="footer" /></footer>
      </div>
    </div>
  </Teleport>
</template>
