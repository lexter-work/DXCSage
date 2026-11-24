<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { get, post, put } from '../../api'
import StatusPill from '../../components/StatusPill.vue'
import Icon from '../../components/Icon.vue'
import { toast } from '../../toast'

const { name, systemId } = useRoute().params as { name: string; systemId: string }
const base = `api/workflows/${name}/systems/${systemId}`
const guide = ref<any | null>(null), wf = ref<any | null>(null), binding = ref<any | null>(null), values = ref<Record<string, string>>({})

const GROUPS: [string, string[]][] = [['Connection', ['reachable', 'login']], ['Function modules', ['fm_exists', 'fm_authorized']], ['Tables', ['table_readable']], ['Settings', ['setting']]]
const grouped = computed(() => GROUPS.map(([label, kinds]) => [label, (guide.value?.steps ?? []).filter((s: any) => kinds.includes(s.kind))] as const).filter(([, l]) => l.length))
const total = computed(() => guide.value?.steps.length ?? 0)
const passed = computed(() => (guide.value?.steps ?? []).filter((s: any) => s.status === 'pass').length)
const checked = computed(() => (guide.value?.steps ?? []).some((s: any) => s.status))
const firstBad = computed(() => (guide.value?.steps ?? []).find((s: any) => s.status && s.status !== 'pass'))
const headline = computed(() => {
  if (!checked.value) return 'Not checked yet. Run the health check to see what is missing.'
  const n = `${passed.value} of ${total.value} checks pass.`
  if (firstBad.value) return `${n} Fix ${firstBad.value.key || firstBad.value.kind} to finish setup.`
  return binding.value?.status === 'enabled' ? `${n} The workflow is enabled on this system.` : `${n} You can enable the workflow.`
})

// Valid values read from the system for settings that support a lookup (for example the report variants).
const opts = ref<Record<string, { loading: boolean; list: string[]; error: string | null }>>({})
async function loadOptions(key: string) {
  opts.value[key] = { loading: true, list: [], error: null }
  try {
    const r = await get<{ options: string[]; error: string | null }>(`${base}/settings/${key}/options`)
    opts.value[key] = { loading: false, list: r.options, error: r.error }
  } catch (e: any) { opts.value[key] = { loading: false, list: [], error: e?.detail ?? String(e) } }
}
const lookup = (key: string) => opts.value[key]
const missing = (key: string) => !!values.value[key] && !!lookup(key) && !lookup(key).error && !lookup(key).list.includes(values.value[key])

async function load() {
  guide.value = await get(`${base}/guide`)
  wf.value = (await get<any[]>('api/workflows')).find(w => w.name === name)
  binding.value = wf.value.bindings.find((b: any) => String(b.system_id) === systemId)
  values.value = { ...(binding.value?.settings ?? {}) }
  for (const s of wf.value.settings) if (s.lookup && !opts.value[s.key]) loadOptions(s.key)
}
async function saveSettings() { try { await put(base, { settings: values.value }); toast('Settings saved'); await load() } catch (e) { toast(e) } }
async function check() { try { await post(`${base}/check`); await load() } catch (e) { toast(e) } }
async function enable() { try { await post(`${base}/enable`); toast('Enabled'); await load() } catch (e) { toast(e) } }
async function disable() { await post(`${base}/disable`); await load() }
async function copyMarkdown() {
  try { await navigator.clipboard.writeText(await get(`${base}/guide?format=markdown`)); toast('Guide copied as Markdown') } catch (e) { toast(e) }
}
async function copyAuth() {
  const rows = (guide.value?.auth_table ?? []).map((r: string[]) => r.join('\t')).join('\n')
  try { await navigator.clipboard.writeText('Object\tField\tValue\n' + rows); toast('Authorization table copied') } catch (e) { toast(e) }
}
onMounted(() => load().catch(toast))
</script>
<template>
  <section v-if="guide" class="page">
    <div class="crumb"><router-link to="/admin/workflows">Workflows</router-link><span>/</span><span class="mono">{{ guide.workflow }}</span><span>/</span><span>{{ guide.system.label }}</span></div>
    <div class="head"><div><h1><span class="mono">{{ guide.workflow }}</span> on {{ guide.system.label }}</h1><p>{{ guide.description }}</p></div></div>
    <p class="bigline">{{ headline }}</p>
    <div class="bar-prog" aria-hidden="true"><i :style="{ width: total ? (100 * passed / total) + '%' : '0%' }" /></div>
    <span class="muted" style="font-size:12.5px">{{ guide.system.sid }} · client {{ guide.system.client }} · RFC user <span class="mono">{{ guide.system.rfc_user }}</span></span>
    <div class="actbar">
      <StatusPill :status="binding?.status" /><span class="muted" style="font-size:12.5px">health</span><StatusPill :status="binding?.health" :label="binding?.health === 'unknown' ? 'Not checked' : undefined" />
      <span class="sp" />
      <button class="btn" @click="check">Run health check</button>
      <button class="btn" @click="copyMarkdown">Copy guide as Markdown</button>
      <button v-if="binding?.status !== 'enabled'" class="btn primary" @click="enable">Enable</button>
      <button v-else class="btn danger" @click="disable">Disable</button>
    </div>

    <div class="guide">
      <div>
        <template v-for="[group, list] in grouped" :key="group">
          <div class="sgroup">{{ group }}</div>
          <div v-for="(s, i) in list" :key="group + i" class="req" :class="s.status === 'pass' ? 'pass' : s.status === 'warn' ? 'warn' : s.status ? 'fail' : 'none'">
            <span class="mark"><Icon :name="s.status === 'pass' ? 'check' : s.status ? 'alert' : 'chev'" /></span>
            <span class="t"><span v-if="s.key">{{ s.kind }}:</span> {{ s.key || s.kind }}</span>
            <StatusPill :status="s.status" :label="s.status ? undefined : 'Not checked'" />
            <span class="x">{{ s.text }}</span>
            <span v-if="s.message" class="m">Last check: {{ s.message }}</span>
            <details v-if="s.source_text"><summary>ABAP source ({{ s.source }})</summary><pre>{{ s.source_text }}</pre></details>
            <span v-if="s.kind === 'setting' && wf?.settings.length" class="x"><button class="btn sm" style="margin-top:6px" @click="($refs['set_' + s.key] as any)?.[0]?.focus()">Set {{ s.key.replace(/_/g, ' ') }}</button></span>
          </div>
        </template>
      </div>
      <div class="gside">
        <div v-if="wf?.settings.length" class="sidecard"><h3>Settings for this system</h3><div class="in">
          <label v-for="s in wf.settings" :key="s.key" class="lbl">{{ s.label }}
            <select v-if="s.lookup && lookup(s.key) && !lookup(s.key).error" :ref="'set_' + s.key" v-model="values[s.key]" class="field mono" :disabled="lookup(s.key).loading">
              <option value="">{{ lookup(s.key).loading ? 'Reading variants from SAP…' : lookup(s.key).list.length ? 'Choose a variant' : 'No variants found' }}</option>
              <option v-if="missing(s.key)" :value="values[s.key]">{{ values[s.key] }} (not found on this system)</option>
              <option v-for="o in lookup(s.key).list" :key="o" :value="o">{{ o }}</option>
            </select>
            <input v-else :ref="'set_' + s.key" v-model="values[s.key]" class="field mono">
            <span class="help">{{ s.description }}</span>
            <span v-if="s.lookup && lookup(s.key)?.error" class="help bad">Could not read the list from SAP ({{ lookup(s.key).error }}). Type the name instead.</span>
            <span v-else-if="s.lookup && lookup(s.key) && !lookup(s.key).loading && !lookup(s.key).list.length" class="help">No variant exists for RC_COLLECT_ANALYSIS_DATA on this system. Create one in SA38, then reload.</span>
            <span v-if="missing(s.key)" class="help bad">This variant is not on the system. The workflow will fail until it exists.</span>
            <button v-if="s.lookup" type="button" class="btn sm" style="justify-self:start" :disabled="lookup(s.key)?.loading" @click="loadOptions(s.key)">Reload from SAP</button>
          </label>
          <div><button class="btn sm" @click="saveSettings">Save settings</button></div></div></div>
        <div class="sidecard"><h3>Authorizations for the RFC user's role<span class="sp" /><button class="btn sm ghost" @click="copyAuth">Copy</button></h3>
          <div class="tablewrap"><table><thead><tr><th>Object</th><th>Field</th><th>Value</th></tr></thead><tbody>
            <tr v-for="(r, i) in guide.auth_table" :key="i"><td class="mono">{{ r[0] }}</td><td class="mono">{{ r[1] }}</td><td class="mono">{{ r[2] }}</td></tr></tbody></table></div>
          <div class="in" style="padding-top:8px"><span class="help">Hand this table to Basis.</span></div></div>
      </div>
    </div>
  </section>
</template>
