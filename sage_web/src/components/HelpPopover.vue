<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from 'vue'
import type { SettingHelp } from '../settingsHelp'
import HelpBody from './HelpBody.vue'
import Icon from './Icon.vue'

const props = defineProps<{ title: string; help: SettingHelp }>()
const open = ref(false), btn = ref<HTMLElement | null>(null), pop = ref<HTMLElement | null>(null)
const pos = ref({ top: 0, left: 0, width: 340 })
const id = `help-${props.title.replace(/[^a-z0-9]/gi, '-')}`

function place() {
  const b = btn.value!.getBoundingClientRect()
  const width = Math.min(360, window.innerWidth - 24)
  const left = Math.min(Math.max(12, b.left - 8), window.innerWidth - width - 12)
  const h = pop.value?.offsetHeight ?? 0
  let top = b.bottom + 8
  if (top + h > window.innerHeight - 12) top = Math.max(12, b.top - h - 8)   // flip above when there is no room below
  pos.value = { top, left, width }
}
const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); close(true) } }
const onOutside = (e: Event) => { const t = e.target as Node; if (!pop.value?.contains(t) && !btn.value?.contains(t)) close(false) }
async function show() {
  open.value = true
  await nextTick(); place()
  window.addEventListener('keydown', onKey, true)
  document.addEventListener('pointerdown', onOutside, true)
  window.addEventListener('resize', onResize)
  window.addEventListener('scroll', onResize, true)
}
const onResize = () => close(false)
function close(refocus: boolean) {
  open.value = false
  window.removeEventListener('keydown', onKey, true)
  document.removeEventListener('pointerdown', onOutside, true)
  window.removeEventListener('resize', onResize)
  window.removeEventListener('scroll', onResize, true)
  if (refocus) btn.value?.focus()
}
function toggle() { open.value ? close(false) : show() }
onBeforeUnmount(() => close(false))
</script>
<template>
  <button ref="btn" type="button" class="help-btn" :aria-expanded="open" :aria-controls="id" :aria-label="`About ${title}`"
          @click.stop="toggle" @keydown.enter.stop @keydown.space.stop><Icon name="help" /></button>
  <Teleport to="body">
    <div v-if="open" :id="id" ref="pop" class="help-pop" role="dialog" :aria-label="`About ${title}`"
         :style="{ top: pos.top + 'px', left: pos.left + 'px', width: pos.width + 'px' }">
      <h4>{{ title }}</h4>
      <HelpBody :help="help" />
    </div>
  </Teleport>
</template>
