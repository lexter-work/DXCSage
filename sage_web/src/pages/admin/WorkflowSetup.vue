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

const GROUPS: [string, string[]][] = [['Connection', ['reachable', 'login']], ['Function modules', ['fm_exists', 'fm_authorized']], ['Tables', ['table_readable']], ['Authorizations', ['auth_declared', 'auth_coverage']], ['Settings', ['setting']]]
const grouped = computed(() => GROUPS.map(([label, kinds]) => [label, (guide.value?.steps ?? []).filter((s: any) => kinds.includes(s.kind))] as const).filter(([, l]) => l.length))
const total = computed(() => guide.value?.steps.length ?? 0)
const passed = computed(() => (guide.value?.steps ?? []).filter((s: any) => s.status === 'pass').length)
const checked = computed(() => (guide.value?.steps ?? []).some((s: any) => s.status))
const firstBad = computed(() => (guide.value?.steps ?? []).find((s: any) => s.status && s.status !== 'pass'))
const headline = computed(() => {
  if (!checked.value) return 'Not checked yet. Run the health check to see what is missing.'
  const n = `${passed.value} of ${total.value} checks pass.`
  if (firstBad.value) return `${n} Fix ${firstBad.value.kind === 'auth_coverage' ? 'the missing authorizations' : firstBad.value.name || firstBad.value.key || firstBad.value.kind} to finish setup.`
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

// Custom ABAP objects have a fixed ID (abap_object_id). A system may name them differently; the ID stays the reference.
const names = ref<Record<string, string>>({}), nameErr = ref<Record<string, string>>({}), savingNames = ref(false)
const NAME_ERR: Record<string, string> = {
  bad_abap_name: 'Use letters, digits and underscores, starting with a letter (an optional /NAMESPACE/ prefix is allowed), up to 30 characters.',
  name_in_use: 'Another object on this system already has this name.',
  unknown_object: 'This object is not used by any workflow.',
}
const dirtyObjects = computed(() => (guide.value?.abap_objects ?? []).filter((o: any) => (names.value[o.object_id] ?? '').trim().toUpperCase() !== o.name))
async function saveNames() {
  nameErr.value = {}; savingNames.value = true
  const failed: Record<string, string> = {}
  for (const o of dirtyObjects.value) {
    try { await put(`api/systems/${systemId}/abap-names`, { object_id: o.object_id, name: names.value[o.object_id] }) }
    catch (e: any) { nameErr.value[o.object_id] = NAME_ERR[e?.detail] ?? e?.detail ?? 'Could not save this name.'; failed[o.object_id] = names.value[o.object_id] }
  }
  savingNames.value = false
  await load()
  Object.assign(names.value, failed)                    // keep what the admin typed where saving failed
  if (!Object.keys(failed).length) toast('Names saved. Health was checked again with them.')
}

async function load() {
  guide.value = await get(`${base}/guide`)
  names.value = Object.fromEntries(guide.value.abap_objects.map((o: any) => [o.object_id, o.name]))
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

// Authorization values the workflow needs, compared with the RFC user (filled by the health check).
const ORDER: Record<string, number> = { missing: 0, unknown: 1, review: 2, granted: 3 }
const STATUS_LABEL: Record<string, string> = { granted: 'Granted', missing: 'Missing', review: 'To review', unknown: 'Unknown' }
const cov = computed(() => (guide.value?.auth_coverage?.rows ?? []) as any[])
const covValues = computed(() => cov.value.filter(r => r.object))
const covNotes = computed(() => cov.value.filter(r => !r.object))
const count = (s: string) => covValues.value.filter(r => r.status === s).length
const needAction = computed(() => covValues.value.filter(r => r.status !== 'granted'))
const showGranted = ref(false)
const shown = computed(() => [...covValues.value].filter(r => showGranted.value || r.status !== 'granted' || !needAction.value.length)
  .sort((a, b) => ORDER[a.status] - ORDER[b.status] || a.object.localeCompare(b.object) || a.field.localeCompare(b.field)))

/** One request for the security team: every missing value now, grouped by object, instead of one blocker per run. */
function requestText(): string {
  const lines = (rows: any[]) => {
    const byObj: Record<string, Record<string, string[]>> = {}
    for (const r of rows) { const f = ((byObj[r.object] ??= {})[r.field] ??= []); if (!f.includes(r.value)) f.push(r.value) }
    return Object.entries(byObj).flatMap(([o, fs]) => [o, ...Object.entries(fs).map(([f, v]) => `  ${f} = ${v.join(', ')}`)])
  }
  const s = guide.value.system
  const add = covValues.value.filter(r => r.status === 'missing')
  const confirm = covValues.value.filter(r => r.status === 'unknown' || r.status === 'review')
  const out = [`Authorization request for RFC user ${s.rfc_user}`, `System: ${s.label} (${s.sid}), client ${s.client}`,
    `Needed by: workflow ${guide.value.workflow}, which calls custom function modules over RFC.`, '']
  if (add.length) out.push(`Please add these authorization values to a role of ${s.rfc_user}:`, ...lines(add), '')
  if (confirm.length) out.push('Please confirm the user has these (they could not be verified, or the value is decided at run time):', ...lines(confirm), '')
  if (covNotes.value.length) out.push('Calls the scan could not follow, so checks behind them are not listed:', ...covNotes.value.map(n => `  ${n.value}`), '')
  return out.join('\n').trimEnd() + '\n'
}
async function copyRequest() {
  try { await navigator.clipboard.writeText(requestText()); toast('Request copied. Paste it into your ticket for the security team.') } catch (e) { toast(e) }
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
            <span class="t"><span v-if="s.key">{{ s.kind }}:</span> {{ s.name || s.key || s.kind }}</span>
            <StatusPill :status="s.status" :label="s.status ? undefined : 'Not checked'" />
            <span v-if="s.key && s.name !== s.key" class="x mono" style="font-size:12px">Object ID {{ s.key }}</span>
            <span class="x">{{ s.text }}</span>
            <span v-if="s.message" class="m">Last check: {{ s.message }}</span>
            <details v-if="s.source_text"><summary>ABAP source ({{ s.source }})</summary><pre>{{ s.source_text }}</pre></details>
            <span v-if="s.kind === 'setting' && wf?.settings.length" class="x"><button class="btn sm" style="margin-top:6px" @click="($refs['set_' + s.key] as any)?.[0]?.focus()">Set {{ s.key.replace(/_/g, ' ') }}</button></span>
          </div>
        </template>
      </div>
      <div class="gside">
        <div v-if="guide.abap_objects.length" class="sidecard"><h3>Object names on this system</h3>
          <form class="in" @submit.prevent="saveNames">
            <p class="help" style="margin:0"><router-link :to="{ path: '/admin/abap', query: { system: systemId } }">Process flow, code and how to create each object</router-link></p>
            <p class="help" style="margin:0">Each custom ABAP object has a fixed ID. If this system names it differently, enter that name. Sage calls and checks the system's name and keeps the ID. This applies to every workflow on this system.</p>
            <div v-for="o in guide.abap_objects" :key="o.object_id" class="lbl">
              <label :for="'an-' + o.object_id">{{ o.kind === 'function_group' ? 'Function group' : 'Function module' }} · ID <span class="mono">{{ o.object_id }}</span></label>
              <div class="rowx">
                <input :id="'an-' + o.object_id" v-model="names[o.object_id]" class="field mono" style="flex:1;min-width:0" maxlength="30" autocapitalize="characters"
                       spellcheck="false" autocomplete="off" :aria-invalid="!!nameErr[o.object_id]" :aria-describedby="nameErr[o.object_id] ? 'ane-' + o.object_id : undefined">
                <button v-if="names[o.object_id] !== o.object_id" type="button" class="btn sm ghost" @click="names[o.object_id] = o.object_id">Use ID</button>
              </div>
              <span v-if="nameErr[o.object_id]" :id="'ane-' + o.object_id" class="help bad" role="alert">{{ nameErr[o.object_id] }}</span>
            </div>
            <div><button class="btn sm" :disabled="!dirtyObjects.length || savingNames">Save names</button></div>
          </form></div>
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
        <div v-if="covValues.length" class="sidecard"><h3>Authorizations for the RFC user<span class="sp" />
            <button class="btn sm" :disabled="!needAction.length" @click="copyRequest">Copy request for security</button></h3>
          <div class="in" style="padding-bottom:0">
            <p class="authsum"><b>{{ count('missing') }}</b> missing · <b>{{ count('unknown') + count('review') }}</b> to review · <b>{{ count('granted') }}</b> granted</p>
            <p class="help" style="margin:0">All values this workflow needs on {{ guide.system.label }}, compared with {{ guide.system.rfc_user }} when the health check last ran. Send the missing ones in one request.</p>
            <label v-if="needAction.length && count('granted')" class="chk"><input v-model="showGranted" type="checkbox"> Show the {{ count('granted') }} granted values</label>
          </div>
          <div class="tablewrap"><table><thead><tr><th>Object</th><th>Field</th><th>Value</th><th>Status</th></tr></thead><tbody>
            <tr v-for="(r, i) in shown" :key="i">
              <td class="mono">{{ r.object }}</td><td class="mono">{{ r.field }}</td>
              <td><span class="mono">{{ r.value }}</span><span v-if="r.source" class="help block">Needed by {{ r.source }}<template v-if="r.note"> · {{ r.note }}</template></span></td>
              <td><StatusPill :status="r.status" :label="STATUS_LABEL[r.status]" /></td></tr></tbody></table></div>
          <div v-if="covNotes.length" class="in" style="padding-top:8px"><span class="help"><b>Not followed by the scan</b> (checks behind these calls are not listed):</span>
            <span v-for="(n, i) in covNotes" :key="i" class="help mono block">{{ n.value }}</span></div>
          <div class="in" style="padding-top:8px"><span class="help">Granted is checked per field, not per authorization, so a missing value is reliable and a granted one is optimistic. Values read from the system's own checks come from <span class="mono">ZFM_AUTH_REQ_LIST</span>.</span></div></div>
        <div v-else class="sidecard"><h3>Authorizations for the RFC user's role<span class="sp" /><button class="btn sm ghost" @click="copyAuth">Copy</button></h3>
          <div class="tablewrap"><table><thead><tr><th>Object</th><th>Field</th><th>Value</th></tr></thead><tbody>
            <tr v-for="(r, i) in guide.auth_table" :key="i"><td class="mono">{{ r[0] }}</td><td class="mono">{{ r[1] }}</td><td class="mono">{{ r[2] }}</td></tr></tbody></table></div>
          <div class="in" style="padding-top:8px"><span class="help">Run the health check to compare these with the RFC user and list everything that is missing.</span></div></div>
      </div>
    </div>
  </section>
</template>
