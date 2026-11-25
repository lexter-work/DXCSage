<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get } from '../../api'
import { toast } from '../../toast'

const route = useRoute()
const systems = ref<any[]>([]), workflows = ref<any[]>([]), list = ref<any[]>([]), doc = ref<any | null>(null)
const systemId = ref<number | ''>(route.query.system ? Number(route.query.system) : '')
const workflow = ref<string>(String(route.query.workflow ?? ''))
const pick = ref<string>(String(route.query.object ?? ''))
const TABS = [['flow', 'Process flow'], ['create', 'How to create it'], ['code', 'ABAP code']] as const
const tab = ref<(typeof TABS)[number][0]>('flow')
const q = () => (systemId.value ? `?system_id=${systemId.value}` : '')
const filtered = computed(() => workflow.value ? list.value.filter(o => o.used_by.includes(workflow.value)) : list.value)

async function loadList() {
  list.value = await get(`api/abap-objects${q()}`)
  if (!filtered.value.some(o => o.object_id === pick.value)) pick.value = filtered.value[0]?.object_id ?? ''
}
async function loadDoc() { doc.value = pick.value ? await get(`api/abap-objects/${pick.value}${q()}`) : null }
async function refresh() { try { await loadList(); await loadDoc() } catch (e) { toast(e) } }
watch(pick, () => loadDoc().catch(toast))
watch(systemId, refresh)
watch(workflow, () => { if (!filtered.value.some(o => o.object_id === pick.value)) pick.value = filtered.value[0]?.object_id ?? '' })
onMounted(async () => {
  systems.value = (await get<any[]>('api/systems')).filter(s => s.status === 'active')
  workflows.value = await get<any[]>('api/workflows')
  await refresh()
})

const code = computed(() => (doc.value?.parts ?? []) as any[])
async function copy(text: string, what: string) { try { await navigator.clipboard.writeText(text); toast(`${what} copied`) } catch (e) { toast(e) } }
function onKey(e: KeyboardEvent) {
  const i = TABS.findIndex(t => t[0] === tab.value), d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
  if (!d) return
  tab.value = TABS[(i + d + TABS.length) % TABS.length][0]
  ;(document.getElementById('tab-' + tab.value) as HTMLElement | null)?.focus()
}
</script>
<template>
  <section class="page">
    <div class="head"><div><h1>ABAP objects</h1><p>The custom function group and function modules an admin creates on each SAP system: what each one does, how to create it, and the code to paste.</p></div></div>
    <div class="abap">
      <aside class="abaplist">
        <label class="lbl" for="abap-sys">Show names for system</label>
        <select id="abap-sys" v-model="systemId" class="field">
          <option value="">Original IDs</option>
          <option v-for="s in systems" :key="s.id" :value="s.id">{{ s.label }} ({{ s.sid }})</option>
        </select>
        <label class="lbl" for="abap-wf">Used by workflow</label>
        <select id="abap-wf" v-model="workflow" class="field">
          <option value="">All workflows</option>
          <option v-for="w in workflows" :key="w.name" :value="w.name">{{ w.name }}</option>
        </select>
        <nav class="objs" aria-label="ABAP objects">
          <button v-for="o in filtered" :key="o.object_id" :class="{ on: o.object_id === pick }" :aria-current="o.object_id === pick ? 'true' : undefined" @click="pick = o.object_id">
            <span class="mono">{{ o.name }}</span>
            <span class="help">{{ o.kind === 'function_group' ? 'Function group' : 'Function module' }}<template v-if="o.name !== o.object_id"> · ID {{ o.object_id }}</template></span>
          </button>
        </nav>
      </aside>
      <div v-if="doc" class="abapdoc panel">
        <div class="in">
          <h2 class="mono" style="margin:0">{{ doc.name }}</h2>
          <p class="desc" style="margin:4px 0 6px"><b>{{ doc.title }}.</b> {{ doc.summary }}</p>
          <p class="help" style="margin:0">{{ doc.kind === 'function_group' ? 'Function group' : 'Function module' }}<template v-if="doc.name !== doc.object_id"> · ID <span class="mono">{{ doc.object_id }}</span></template>
            · Used by {{ doc.used_by.length ? doc.used_by.join(', ') : 'no installed workflow' }}</p>
        </div>
        <div class="tabs" role="tablist" aria-label="Documentation" @keydown="onKey">
          <button v-for="t in TABS" :id="'tab-' + t[0]" :key="t[0]" role="tab" :aria-selected="tab === t[0]" :aria-controls="'pan-' + t[0]" :tabindex="tab === t[0] ? 0 : -1" @click="tab = t[0]">{{ t[1] }}</button>
        </div>

        <div v-show="tab === 'flow'" id="pan-flow" role="tabpanel" aria-labelledby="tab-flow" class="in">
          <ol class="flow"><li v-for="(s, i) in doc.flow" :key="i"><b>{{ s.title }}</b><span>{{ s.text }}</span></li></ol>
          <template v-if="doc.interface">
            <h3 class="sub">Interface</h3>
            <div class="tablewrap"><table><thead><tr><th>Direction</th><th>Parameter</th><th>Type</th><th>Required</th></tr></thead><tbody>
              <tr v-for="p in doc.interface.importing" :key="'i' + p.name"><td>Import</td><td class="mono">{{ p.name }}</td><td class="mono">{{ p.type }}</td><td>{{ p.optional ? 'Optional' : 'Required' }}<span v-if="p.note" class="help block">{{ p.note }}</span></td></tr>
              <tr v-for="p in doc.interface.exporting" :key="'e' + p.name"><td>Export</td><td class="mono">{{ p.name }}</td><td class="mono">{{ p.type }}</td><td>{{ p.optional ? 'Optional' : '' }}<span v-if="p.note" class="help block">{{ p.note }}</span></td></tr>
              <tr v-for="x in doc.interface.exceptions" :key="x"><td>Exception</td><td class="mono" colspan="3">{{ x }}</td></tr>
            </tbody></table></div>
          </template>
        </div>

        <div v-show="tab === 'create'" id="pan-create" role="tabpanel" aria-labelledby="tab-create" class="in">
          <ol class="flow"><li v-for="(s, i) in doc.create" :key="i"><b>{{ s.title }}</b><span>{{ s.text }}</span></li></ol>
          <template v-if="doc.notes.length"><h3 class="sub">Before you rely on it</h3><ul class="notes"><li v-for="(n, i) in doc.notes" :key="i">{{ n }}</li></ul></template>
        </div>

        <div v-show="tab === 'code'" id="pan-code" role="tabpanel" aria-labelledby="tab-code" class="in">
          <p v-if="!code.length" class="muted">This object has no code. It is created empty.</p>
          <div v-for="p in code" :key="p.label" class="codepart">
            <h3 class="sub">{{ p.label }}<span class="sp" /><button class="btn sm" @click="copy(p.code, p.label)">Copy</button></h3>
            <p class="help" style="margin:0 0 6px">Paste into: {{ p.where }}</p>
            <pre tabindex="0" :aria-label="p.label">{{ p.code }}</pre>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
