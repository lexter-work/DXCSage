<script setup lang="ts">
import type { SettingHelp } from '../settingsHelp'
defineProps<{ help: SettingHelp }>()
</script>
<template>
  <div class="helpbody">
    <p>{{ help.summary }}</p>
    <dl>
      <template v-if="help.format"><dt>Format</dt><dd>{{ help.format }}</dd></template>
      <dt>Default</dt><dd class="mono">{{ help.fallback }}</dd>
      <template v-if="help.effect"><dt>Effect</dt><dd>{{ help.effect }}</dd></template>
    </dl>
  </div>
</template>
