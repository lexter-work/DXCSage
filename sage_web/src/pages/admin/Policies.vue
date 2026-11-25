<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { del, get, post, put } from '../../api'
import DataTable from '../../components/DataTable.vue'
import Drawer from '../../components/Drawer.vue'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

const policies = ref<any[]>([]), reviews = ref<any[]>([])
const sel = ref<{ id: number | null; name: string; text: string; required: boolean; fingerprint?: string } | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const busy = ref<string | null>(null)

async function load() { policies.value = await get('api/policies') }
function create() { sel.value = { id: null, name: '', text: '', required: false }; reviews.value = [] }
async function open(p: any) { sel.value = { id: p.id, name: p.name, text: p.text, required: p.required, fingerprint: p.fingerprint }; reviews.value = await get(`api/policies/${p.id}/reviews`) }
async function save() {
  busy.value = 'save'
  const p = sel.value!, body = { name: p.name, text: p.text, required: p.required }
  try { p.id ? await put(`api/policies/${p.id}`, body) : await post('api/policies', body); toast('Policy saved. Earlier reviews of the old text no longer count.'); sel.value = null; await load() }
  catch (e) { toast(e) }
  finally { busy.value = null }
}
async function onFile(e: Event) {
  const input = e.target as HTMLInputElement, f = input.files?.[0]
  if (!f || !sel.value) return
  busy.value = 'upload'
  try {
    const r = await fetch(`api/policies/extract?filename=${encodeURIComponent(f.name)}`, { method: 'PUT', credentials: 'same-origin', body: f })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) return toast(j.detail ?? 'The file could not be read.')
    sel.value.text = j.text; if (!sel.value.name) sel.value.name = f.name.replace(/\.[^.]+$/, '')
  } finally { input.value = ''; busy.value = null }
}
async function clear() {
  busy.value = 'clear'
  try { await post(`api/policies/${sel.value!.id}/clear-reviews`); reviews.value = []; toast('Reviews cleared. The next request is reviewed again.'); await load() }
  catch (e) { toast(e) }
  finally { busy.value = null }
}
async function remove() {
  busy.value = 'remove'
  try { await del(`api/policies/${sel.value!.id}`); toast('Policy deleted'); sel.value = null; await load() }
  catch (e) { toast(e) }
  finally { busy.value = null }
}
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="head"><div><h1>Policies</h1><p>Written company rules for role and user-role changes. The structured rules (restricted objects, wildcards, activity levels) are checked by code. These documents are read by the AI in the chat, against each request.</p></div>
      <span class="sp" /><button class="btn primary" @click="create">New policy</button></div>
    <div class="callout info"><span>How it works: when a request is reviewed, the AI reads each required policy, compares it with the exact changes, and records its findings. A finding blocks the change. A verdict counts only for that exact request and that exact text, so editing the policy asks for a new review. It is an AI judgment, not an access control: the structured checks and the review gate stay in force.</span></div>

    <DataTable clickable :rows="policies" :columns="[{key:'name',label:'Policy'},{key:'required',label:'Applies to'},{key:'reviews',label:'Reviews recorded',num:true},{key:'updated_at',label:'Updated',mono:true}]" @select="open">
      <template #required="{ row }"><StatusPill :status="row.required ? 'ok' : 'off'" :label="row.required ? 'Every request' : 'On request only'" /></template>
    </DataTable>
    <p v-if="!policies.length" class="muted">No policy yet. Role and user-role changes are then checked by the structured rules only.</p>

    <Drawer :open="!!sel" :title="sel?.id ? sel.name : 'New policy'" @close="sel = null">
      <template v-if="sel">
        <label class="lbl">Name<input v-model="sel.name" class="field" maxlength="60"></label>
        <label class="chk"><input v-model="sel.required" type="checkbox"> Check every role and user-role request against this policy</label>
        <p class="help" style="margin:0">Without the tick, a policy is only checked when someone names it in the request.</p>
        <div class="rowx"><input ref="fileInput" type="file" accept=".txt,.md,.docx" hidden @change="onFile"><button class="btn sm" :disabled="busy==='upload'" @click="fileInput?.click()"><span v-if="busy==='upload'" class="spinner" />Load text from a file</button><span class="help">.txt, .md or .docx</span></div>
        <label class="lbl">Policy text<textarea v-model="sel.text" class="field" rows="14" maxlength="60000" spellcheck="true" /></label>
        <p v-if="sel.fingerprint" class="help" style="margin:0">Fingerprint <span class="mono">{{ sel.fingerprint }}</span></p>
        <template v-if="sel.id">
          <h3>Recorded reviews ({{ reviews.length }})</h3>
          <p v-if="!reviews.length" class="muted">None for the current text.</p>
          <ul v-else class="members"><li v-for="(r, i) in reviews" :key="i"><span><b>{{ r.kind === 'user_role' ? 'User roles' : 'Role authorizations' }}</b> <span class="help mono">{{ r.request_hash }}</span>
            <span class="help block">{{ r.created_at }} · {{ r.reviewed_by }} · {{ r.findings.length ? r.findings.length + ' finding(s)' : 'no findings' }}</span>
            <span v-for="(f, j) in r.findings" :key="j" class="help block bad">{{ f.role ? f.role + ': ' : '' }}{{ f.description }}</span></span></li></ul>
        </template>
      </template>
      <template #footer><button v-if="sel?.id" class="btn danger" :disabled="busy==='remove'" @click="remove"><span v-if="busy==='remove'" class="spinner" />Delete</button><button v-if="sel?.id" class="btn" :disabled="busy==='clear'" @click="clear"><span v-if="busy==='clear'" class="spinner" />Clear reviews</button><span class="sp" />
        <button class="btn" @click="sel = null">Cancel</button><button class="btn primary" :disabled="!sel?.name.trim() || !sel?.text.trim() || busy==='save'" @click="save"><span v-if="busy==='save'" class="spinner" />Save</button></template>
    </Drawer>
  </section>
</template>
