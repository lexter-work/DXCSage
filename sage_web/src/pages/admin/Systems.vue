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
    <div class="page-head"><div><h1>Systems</h1><p>SAP systems Sage can reach through one RFC account each. Systems are disabled, never deleted.</p></div><span class="spacer" />
      <button class="btn primary" @click="creating = true">Register system</button></div>
    <DataTable clickable :rows="systems" @select="open" :columns="[{key:'label',label:'Label',mono:true},{key:'sid',label:'SID',mono:true},{key:'ashost',label:'Host',mono:true},{key:'client',label:'Client',mono:true},{key:'rfc_user',label:'RFC user',mono:true},{key:'status',label:'Status'}]">
      <template #status="{ row }"><StatusPill :status="row.status" /></template>
    </DataTable>

    <Drawer :open="creating" title="Register system" @close="creating = false">
      <label class="lbl">Label (for example TS3)<input class="field" v-model="form.label"></label>
      <label class="lbl">SID<input class="field" v-model="form.sid" maxlength="3"></label>
      <label class="lbl">Description<input class="field" v-model="form.description"></label>
      <label class="lbl">Application server host<input class="field" v-model="form.ashost"></label>
      <div class="row"><label class="lbl">System number<input class="field" v-model="form.sysnr" maxlength="2"></label>
        <label class="lbl">Client<input class="field" v-model="form.client" maxlength="3"></label></div>
      <div class="callout info"><span>The RFC account Sage logs in with. The password is stored encrypted and is never shown again.</span></div>
      <label class="lbl">RFC user<input class="field" v-model="form.rfc_user" autocomplete="off"></label>
      <label class="lbl">RFC password<input class="field" type="password" v-model="form.rfc_password" autocomplete="new-password"></label>
      <button class="btn primary" @click="create">Register and test connection</button>
    </Drawer>

    <Drawer :open="!!sel" :title="sel?.label ?? ''" @close="sel = null">
      <template v-if="sel">
        <div class="row"><StatusPill :status="sel.status" /><button class="btn sm" @click="test">Test connection</button>
          <button v-if="sel.status !== 'active'" class="btn sm" @click="setStatus('active')">Activate</button>
          <button v-if="sel.status !== 'disabled'" class="btn sm danger" @click="setStatus('disabled')">Disable</button></div>
        <div v-if="testMsg" class="callout info"><span>{{ testMsg }}</span></div>
        <label class="lbl">Label<input class="field" v-model="sel.label"></label>
        <label class="lbl">SID<input class="field" v-model="sel.sid" maxlength="3"></label>
        <label class="lbl">Description<input class="field" v-model="sel.description"></label>
        <label class="lbl">Host<input class="field" v-model="sel.ashost"></label>
        <div class="row"><label class="lbl">System number<input class="field" v-model="sel.sysnr"></label><label class="lbl">Client<input class="field" v-model="sel.client"></label></div>
        <button class="btn" @click="save">Save details</button>
        <h3 style="margin:8px 0 0;font-size:14px">RFC account</h3>
        <label class="lbl">RFC user<input class="field" v-model="cred.user" autocomplete="off"></label>
        <label class="lbl">New RFC password<input class="field" type="password" v-model="cred.password" autocomplete="new-password"></label>
        <button class="btn" :disabled="!cred.user || !cred.password" @click="rotate">Update credentials</button>
      </template>
    </Drawer>
  </section>
</template>
