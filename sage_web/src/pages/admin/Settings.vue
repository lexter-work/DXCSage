<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { get, put } from '../../api'
import Drawer from '../../components/Drawer.vue'
import HelpBody from '../../components/HelpBody.vue'
import HelpPopover from '../../components/HelpPopover.vue'
import { SETTINGS_HELP } from '../../settingsHelp'
import { toast } from '../../toast'

const raw = ref<Record<string, any>>({}), sel = ref<string | null>(null), text = ref('')
const isSecret = (v: any) => v && typeof v === 'object' && 'set' in v && Object.keys(v).length === 1
const GROUPS: [string, string[]][] = [['Providers', ['providers.']], ['Agent and waiting', ['agent.', 'wait.']], ['SAP and health', ['sap.', 'health.']], ['Workflows', ['workflows.', 'readiness.', 'sod.']]]
const grouped = computed(() => GROUPS.map(([label, prefixes]) => [label, Object.entries(raw.value).filter(([k]) => prefixes.some(p => k.startsWith(p))).map(([key, v]) => ({
  key, secret: isSecret(v), set: isSecret(v) && v.set, value: JSON.stringify(v),
}))] as const).filter(([, l]) => l.length))
const missing = computed(() => [['providers.anthropic_api_key', 'Claude'], ['providers.openai_api_key', 'GPT']].filter(([k]) => raw.value[k] && !raw.value[k].set))
const title = computed(() => !Object.keys(raw.value).length ? 'Settings' : missing.value.length === 2 ? 'Claude and GPT have no API key yet' : missing.value.length ? `${missing.value[0][1]} has no API key yet` : 'Settings')
const load = async () => (raw.value = await get('api/settings'))
function open(r: any) { sel.value = r.key; text.value = r.secret ? '' : JSON.stringify(raw.value[r.key], null, 2) }
async function save() {
  const secret = isSecret(raw.value[sel.value!])
  try {
    await put('api/settings', { key: sel.value, value: secret ? text.value : JSON.parse(text.value) })
    toast('Saved'); sel.value = null; await load()
  } catch (e) { toast(e instanceof SyntaxError ? 'The value is not valid JSON.' : e) }
}
const short = (v: string) => v.length > 110 ? v.slice(0, 110) + '…' : v
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="head"><div><h1>{{ title }}</h1><p>All configuration lives here. Secret values are write-only. Every change is written to the audit log as config.change.</p></div></div>
    <div v-if="missing.length" class="callout" style="margin-bottom:16px"><span><template v-for="([k, n], i) in missing" :key="k"><b>{{ k }} is not set.</b> <template v-if="i === missing.length - 1">Users can only start {{ missing.length === 2 ? 'no' : n === 'GPT' ? 'Claude' : 'GPT' }} chats until you add it.</template></template></span></div>
    <div class="panel tablewrap"><table>
      <thead><tr><th style="width:280px">Setting</th><th>Value</th></tr></thead>
      <tbody>
        <template v-for="[label, list] in grouped" :key="label">
          <tr class="grp"><td colspan="2">{{ label }}</td></tr>
          <tr v-for="r in list" :key="r.key" class="click" tabindex="0" @click="open(r)" @keydown.enter="open(r)">
            <td><span class="keycell"><span class="mono">{{ r.key }}</span><HelpPopover v-if="SETTINGS_HELP[r.key]" :title="r.key" :help="SETTINGS_HELP[r.key]" /></span></td>
            <td class="wrap" style="color:var(--ink)"><span v-if="r.secret" class="pill" :class="r.set ? 'ok' : 'warn'">{{ r.set ? 'Set' : 'Not set' }}</span><span v-else class="mono">{{ short(r.value) }}</span></td>
          </tr>
        </template>
      </tbody></table></div>

    <Drawer :open="!!sel" :title="sel ?? ''" mono @close="sel = null">
      <div v-if="sel && SETTINGS_HELP[sel]" class="drawerhelp"><HelpBody :help="SETTINGS_HELP[sel]" /></div>
      <label v-if="!isSecret(raw[sel ?? ''])" class="lbl">Value (JSON)<textarea v-model="text" class="field" rows="16" spellcheck="false" /></label>
      <label v-else class="lbl">New secret value (never shown again)<input v-model="text" class="field" type="password" autocomplete="new-password"></label>
      <div class="callout info"><span>{{ isSecret(raw[sel ?? '']) ? 'Stored encrypted with the master key. The current value is never shown.' : 'Saved values are validated as JSON. The change is written to the audit log.' }}</span></div>
      <template #footer><button class="btn" @click="sel = null">Cancel</button><button class="btn primary" @click="save">Save</button></template>
    </Drawer>
  </section>
</template>
