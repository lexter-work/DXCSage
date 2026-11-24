<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { get, post, put } from '../../api'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

const { name, systemId } = useRoute().params as { name: string; systemId: string }
const base = `api/workflows/${name}/systems/${systemId}`
const guide = ref<any | null>(null), wf = ref<any | null>(null), binding = ref<any | null>(null), values = ref<Record<string, string>>({})
async function load() {
  guide.value = await get(`${base}/guide`)
  wf.value = (await get<any[]>('api/workflows')).find(w => w.name === name)
  binding.value = wf.value.bindings.find((b: any) => String(b.system_id) === systemId)
  values.value = { ...(binding.value?.settings ?? {}) }
}
async function saveSettings() { try { await put(base, { settings: values.value }); toast('Settings saved'); await load() } catch (e) { toast(e) } }
async function check() { try { await post(`${base}/check`); await load() } catch (e) { toast(e) } }
async function enable() { try { await post(`${base}/enable`); toast('Enabled'); await load() } catch (e) { toast(e) } }
async function disable() { await post(`${base}/disable`); await load() }
async function copyMarkdown() {
  try { await navigator.clipboard.writeText(await get(`${base}/guide?format=markdown`)); toast('Guide copied as Markdown') } catch (e) { toast(e) }
}
onMounted(() => load().catch(toast))
</script>
<template>
  <section class="page" v-if="guide">
    <div class="page-head"><div><h1><span class="mono">{{ guide.workflow }}</span> on {{ guide.system.label }}</h1>
      <p>{{ guide.description }}</p></div><span class="spacer" />
      <router-link class="btn" to="/admin/workflows">Back</router-link></div>
    <div class="card" style="margin-bottom:14px"><div class="card-b row">
      <StatusPill :status="binding?.status" /><span class="muted">health</span><StatusPill :status="binding?.health" />
      <span class="spacer" />
      <button class="btn" @click="check">Run health check</button>
      <button class="btn" @click="copyMarkdown">Copy guide as Markdown</button>
      <button v-if="binding?.status !== 'enabled'" class="btn primary" @click="enable">Enable</button>
      <button v-else class="btn danger" @click="disable">Disable</button>
    </div></div>

    <div v-if="wf?.settings.length" class="card" style="margin-bottom:14px"><div class="card-h"><h2>Settings for this system</h2></div>
      <div class="card-b" style="display:grid;gap:10px">
        <label v-for="s in wf.settings" :key="s.key" class="lbl">{{ s.label }}<input class="field" v-model="values[s.key]">
          <span class="muted">{{ s.description }}</span></label>
        <div><button class="btn" @click="saveSettings">Save settings</button></div>
      </div></div>

    <div class="card" style="margin-bottom:14px"><div class="card-h"><h2>Setup steps on {{ guide.system.sid }} (client {{ guide.system.client }})</h2>
      <span class="sub">RFC user <span class="mono">{{ guide.system.rfc_user }}</span></span></div>
      <div class="card-b" style="display:grid;gap:12px">
        <div v-for="(s, i) in guide.steps" :key="i" style="border-bottom:1px solid var(--line);padding-bottom:10px">
          <div class="row"><b>{{ i + 1 }}. {{ s.title }}</b><StatusPill :status="s.status" /></div>
          <p style="margin:4px 0">{{ s.text }}</p>
          <p v-if="s.message" class="muted mono" style="margin:0">Last check: {{ s.message }}</p>
          <details v-if="s.source_text"><summary>ABAP source ({{ s.source }})</summary><pre class="out">{{ s.source_text }}</pre></details>
        </div>
      </div></div>

    <div class="card"><div class="card-h"><h2>Authorizations for the RFC user's role</h2><span class="sub">Hand this table to Basis</span></div>
      <div class="card-b"><table><thead><tr><th>Object</th><th>Field</th><th>Value</th></tr></thead><tbody>
        <tr v-for="(r, i) in guide.auth_table" :key="i"><td class="mono">{{ r[0] }}</td><td class="mono">{{ r[1] }}</td><td class="mono">{{ r[2] }}</td></tr></tbody></table></div></div>
  </section>
</template>
