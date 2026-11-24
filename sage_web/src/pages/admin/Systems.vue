<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { get, patch, post, put } from '../../api'
import DataTable from '../../components/DataTable.vue'
import Drawer from '../../components/Drawer.vue'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

const systems = ref<any[]>([]), sel = ref<any | null>(null), creating = ref(false)
const blank = () => ({ label: '', sid: '', description: '', ashost: '', sysnr: '00', client: '100', rfc_user: '', rfc_password: '' })
const form = ref(blank()), cred = ref({ user: '', password: '' }), testMsg = ref('')
const load = async () => (systems.value = await get('api/systems'))
async function create() {
  try {
    const r = await post('api/systems', form.value)
    toast(r.test.ok ? `${r.label} registered and active.` : `${r.label} saved as inactive: ${r.test.message || r.test.stage}`)
    creating.value = false; form.value = blank(); await load()
  } catch (e) { toast(e) }
}
function open(s: any) { sel.value = { ...s }; cred.value = { user: s.rfc_user, password: '' }; testMsg.value = '' }
async function save() {
  const { label, sid, description, ashost, sysnr, client } = sel.value
  try { await patch(`api/systems/${sel.value.id}`, { label, sid, description, ashost, sysnr, client }); toast('Saved'); await load() } catch (e) { toast(e) }
}
async function rotate() {
  try { await put(`api/systems/${sel.value.id}/credentials`, cred.value); cred.value.password = ''; toast('Credentials updated. Run a test.') } catch (e) { toast(e) }
}
async function test() { const r = await post(`api/systems/${sel.value.id}/test`); testMsg.value = r.ok ? 'Connected and logged in.' : `${r.stage}: ${r.message}` }
async function setStatus(status: string) {
  try { await post(`api/systems/${sel.value.id}/status`, { status }); sel.value.status = status; await load() } catch (e) { toast(e) }
}
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="head"><div><h1>Systems</h1><p>SAP systems Sage can reach through one RFC account each. Systems are disabled, never deleted.</p></div><span class="sp" />
      <button class="btn primary" @click="creating = true">Register system</button></div>
    <DataTable clickable :rows="systems" :columns="[{key:'label',label:'Label',mono:true},{key:'sid',label:'SID',mono:true},{key:'ashost',label:'Host',mono:true},{key:'sysnr',label:'Sys. no.',num:true},{key:'client',label:'Client',num:true},{key:'rfc_user',label:'RFC user',mono:true},{key:'status',label:'Status'}]" @select="open">
      <template #status="{ row }"><StatusPill :status="row.status" /></template>
    </DataTable>

    <Drawer :open="creating" title="Register system" @close="creating = false">
      <label class="lbl">Label (for example TS3)<input v-model="form.label" class="field mono"></label>
      <label class="lbl">SID<input v-model="form.sid" class="field mono" maxlength="3"></label>
      <label class="lbl">Description<input v-model="form.description" class="field"></label>
      <label class="lbl">Application server host<input v-model="form.ashost" class="field mono"></label>
      <div class="two"><label class="lbl">System number<input v-model="form.sysnr" class="field mono" maxlength="2"></label>
        <label class="lbl">Client<input v-model="form.client" class="field mono" maxlength="3"></label></div>
      <h3>RFC account</h3>
      <div class="callout info"><span>The RFC account Sage logs in with. The password is stored encrypted and is never shown again.</span></div>
      <label class="lbl">RFC user<input v-model="form.rfc_user" class="field mono" autocomplete="off"></label>
      <label class="lbl">RFC password<input v-model="form.rfc_password" class="field" type="password" autocomplete="new-password"></label>
      <template #footer><button class="btn" @click="creating = false">Cancel</button><button class="btn primary" @click="create">Register and test connection</button></template>
    </Drawer>

    <Drawer :open="!!sel" :title="sel?.label ?? ''" @close="sel = null">
      <template #status><StatusPill :status="sel?.status" /></template>
      <template v-if="sel">
        <div class="rowx"><button class="btn sm" @click="test">Test connection</button>
          <button v-if="sel.status !== 'active'" class="btn sm" @click="setStatus('active')">Activate</button>
          <button v-if="sel.status !== 'disabled'" class="btn sm danger" @click="setStatus('disabled')">Disable</button></div>
        <div v-if="testMsg" class="callout info"><span>{{ testMsg }}</span></div>
        <div class="two"><label class="lbl">Label<input v-model="sel.label" class="field mono"></label><label class="lbl">SID<input v-model="sel.sid" class="field mono" maxlength="3"></label></div>
        <label class="lbl">Description<input v-model="sel.description" class="field"></label>
        <label class="lbl">Application server host<input v-model="sel.ashost" class="field mono"></label>
        <div class="two"><label class="lbl">System number<input v-model="sel.sysnr" class="field mono"></label><label class="lbl">Client<input v-model="sel.client" class="field mono"></label></div>
        <h3>RFC account</h3>
        <div class="callout info"><span>The password is stored encrypted and is never shown again.</span></div>
        <label class="lbl">RFC user<input v-model="cred.user" class="field mono" autocomplete="off"></label>
        <label class="lbl">New RFC password<input v-model="cred.password" class="field" type="password" placeholder="Leave blank to keep the current one" autocomplete="new-password"></label>
        <div><button class="btn sm" :disabled="!cred.user || !cred.password" @click="rotate">Update credentials</button></div>
      </template>
      <template #footer><button class="btn" @click="sel = null">Close</button><button class="btn primary" @click="save">Save details</button></template>
    </Drawer>
  </section>
</template>
