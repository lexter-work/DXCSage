<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { del, get, patch, post, put } from '../../api'
import DataTable from '../../components/DataTable.vue'
import Drawer from '../../components/Drawer.vue'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

const systems = ref<any[]>([]), sel = ref<any | null>(null), creating = ref(false)
const blank = () => ({ label: '', sid: '', description: '', ashost: '', sysnr: '00', client: '100', rfc_user: '', rfc_password: '' })
const form = ref(blank()), cred = ref({ user: '', password: '' }), testMsg = ref('')
const busy = ref<string | null>(null)
async function withBusy(key: string, fn: () => Promise<void>) {
  busy.value = key
  try { await fn() } finally { busy.value = null }
}
// Optional SSH access to the host (read files, check processes). Off unless an admin adds it.
const blankSsh = () => ({ host: '', port: 22, user: '', auth: 'password', secret: '' })
const withSsh = ref(false), newSsh = ref(blankSsh())
const ssh = ref<any>({ configured: false }), sshForm = ref(blankSsh()), sshResult = ref<any>(null), sshEditing = ref(false)
const load = async () => (systems.value = await get('api/systems'))
async function create() {
  await withBusy('create', async () => {
    try {
      const r = await post('api/systems', { ...form.value, ...(withSsh.value ? { ssh: { ...newSsh.value, port: Number(newSsh.value.port) } } : {}) })
      toast(r.test.ok ? `${r.label} registered and active.` : `${r.label} saved as inactive: ${r.test.message || r.test.stage}`)
      creating.value = false; form.value = blank(); withSsh.value = false; newSsh.value = blankSsh(); await load()
    } catch (e) { toast(e) }
  })
}
function open(s: any) { sel.value = { ...s }; cred.value = { user: s.rfc_user, password: '' }; testMsg.value = ''; sshResult.value = null; sshEditing.value = false; loadSsh() }
async function loadSsh() {
  try { ssh.value = await get(`api/systems/${sel.value.id}/ssh`); sshForm.value = { ...blankSsh(), host: ssh.value.host ?? '', port: ssh.value.port ?? 22, user: ssh.value.user ?? '', auth: ssh.value.auth ?? 'password' } } catch (e) { toast(e) }
}
async function saveSsh() {
  await withBusy('saveSsh', async () => {
    try {
      ssh.value = await put(`api/systems/${sel.value.id}/ssh`, { ...sshForm.value, port: Number(sshForm.value.port) })
      sshForm.value.secret = ''; sshEditing.value = false; sshResult.value = null; toast('SSH access saved. Test it and trust the host key.'); await load()
    } catch (e) { toast(e) }
  })
}
async function testSsh() {
  await withBusy('testSsh', async () => {
    try { sshResult.value = await post(`api/systems/${sel.value.id}/ssh/test`) } catch (e) { toast(e) }
  })
}
async function trustSsh() {
  await withBusy('trustSsh', async () => {
    try { ssh.value = await post(`api/systems/${sel.value.id}/ssh/trust`, { fingerprint: sshResult.value.fingerprint }); await testSsh() } catch (e) { toast(e) }
  })
}
async function removeSsh() {
  await withBusy('removeSsh', async () => {
    try { await del(`api/systems/${sel.value.id}/ssh`); sshResult.value = null; await loadSsh(); await load(); toast('SSH access removed') } catch (e) { toast(e) }
  })
}
async function save() {
  await withBusy('save', async () => {
    const { label, sid, description, ashost, sysnr, client } = sel.value
    try { await patch(`api/systems/${sel.value.id}`, { label, sid, description, ashost, sysnr, client }); toast('Saved'); await load() } catch (e) { toast(e) }
  })
}
async function rotate() {
  await withBusy('rotate', async () => {
    try { await put(`api/systems/${sel.value.id}/credentials`, cred.value); cred.value.password = ''; toast('Credentials updated. Run a test.') } catch (e) { toast(e) }
  })
}
async function test() {
  await withBusy('test', async () => {
    try { const r = await post(`api/systems/${sel.value.id}/test`); testMsg.value = r.ok ? 'Connected and logged in.' : `${r.stage}: ${r.message}` }
    catch (e) { toast(e) }
  })
}
async function setStatus(status: string) {
  await withBusy('status', async () => {
    try { await post(`api/systems/${sel.value.id}/status`, { status }); sel.value.status = status; await load() } catch (e) { toast(e) }
  })
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
      <h3>SSH access <span class="help">(optional)</span></h3>
      <label class="chk"><input v-model="withSsh" type="checkbox"> Add SSH access to the host of this system</label>
      <template v-if="withSsh">
        <div class="callout info"><span>Only used to read files and check processes on the host, for example the files of SUM. Sage never runs typed commands. After registering, test the connection and trust the host key.</span></div>
        <div class="two"><label class="lbl">SSH host<input v-model="newSsh.host" class="field mono" placeholder="Same as the application server"></label>
          <label class="lbl">Port<input v-model="newSsh.port" class="field mono" inputmode="numeric"></label></div>
        <label class="lbl">SSH user<input v-model="newSsh.user" class="field mono" autocomplete="off"></label>
        <label class="lbl">Sign in with<select v-model="newSsh.auth" class="field"><option value="password">Password</option><option value="key">Private key</option></select></label>
        <label v-if="newSsh.auth === 'password'" class="lbl">SSH password<input v-model="newSsh.secret" class="field" type="password" autocomplete="new-password"></label>
        <label v-else class="lbl">Private key (no passphrase)<textarea v-model="newSsh.secret" class="field mono" rows="5" spellcheck="false" autocomplete="off" /></label>
      </template>
      <template #footer><button class="btn" @click="creating = false">Cancel</button><button class="btn primary" :disabled="busy==='create'" @click="create"><span v-if="busy==='create'" class="spinner" />{{ busy==='create' ? 'Registering…' : 'Register and test connection' }}</button></template>
    </Drawer>

    <Drawer :open="!!sel" :title="sel?.label ?? ''" @close="sel = null">
      <template #status><StatusPill :status="sel?.status" /></template>
      <template v-if="sel">
        <div class="rowx"><button class="btn sm" :disabled="busy==='test'" @click="test"><span v-if="busy==='test'" class="spinner" />{{ busy==='test' ? 'Testing…' : 'Test connection' }}</button>
          <button v-if="sel.status !== 'active'" class="btn sm" :disabled="busy==='status'" @click="setStatus('active')"><span v-if="busy==='status'" class="spinner" />Activate</button>
          <button v-if="sel.status !== 'disabled'" class="btn sm danger" :disabled="busy==='status'" @click="setStatus('disabled')"><span v-if="busy==='status'" class="spinner" />Disable</button></div>
        <div v-if="testMsg" class="callout info"><span>{{ testMsg }}</span></div>
        <div class="two"><label class="lbl">Label<input v-model="sel.label" class="field mono"></label><label class="lbl">SID<input v-model="sel.sid" class="field mono" maxlength="3"></label></div>
        <label class="lbl">Description<input v-model="sel.description" class="field"></label>
        <label class="lbl">Application server host<input v-model="sel.ashost" class="field mono"></label>
        <div class="two"><label class="lbl">System number<input v-model="sel.sysnr" class="field mono"></label><label class="lbl">Client<input v-model="sel.client" class="field mono"></label></div>
        <h3>RFC account</h3>
        <div class="callout info"><span>The password is stored encrypted and is never shown again.</span></div>
        <label class="lbl">RFC user<input v-model="cred.user" class="field mono" autocomplete="off"></label>
        <label class="lbl">New RFC password<input v-model="cred.password" class="field" type="password" placeholder="Leave blank to keep the current one" autocomplete="new-password"></label>
        <div><button class="btn sm" :disabled="!cred.user || !cred.password || busy==='rotate'" @click="rotate"><span v-if="busy==='rotate'" class="spinner" />Update credentials</button></div>
        <h3>SSH access <span class="help">(optional)</span></h3>
        <div class="callout info"><span>Only used to read files and check processes on the host, for example the files of SUM. The secret is stored encrypted and is never shown again. The host key must be trusted before Sage logs in.</span></div>
        <template v-if="ssh.configured && !sshEditing">
          <p class="help" style="margin:0"><span class="mono">{{ ssh.user }}@{{ ssh.host }}:{{ ssh.port }}</span> · {{ ssh.auth === 'key' ? 'private key' : 'password' }} ·
            <StatusPill :status="ssh.trusted ? 'ok' : 'warn'" :label="ssh.trusted ? 'Host key trusted' : 'Host key not trusted'" /></p>
          <p v-if="ssh.trusted" class="help" style="margin:0">Fingerprint <span class="mono">{{ ssh.fingerprint }}</span></p>
          <div class="rowx"><button class="btn sm" :disabled="busy==='testSsh'" @click="testSsh"><span v-if="busy==='testSsh'" class="spinner" />Test SSH</button><button class="btn sm" @click="sshEditing = true">Change</button>
            <button class="btn sm danger" :disabled="busy==='removeSsh'" @click="removeSsh"><span v-if="busy==='removeSsh'" class="spinner" />Remove</button></div>
          <div v-if="sshResult?.ok" class="callout info"><span>Connected and logged in over SSH.</span></div>
          <div v-else-if="sshResult" class="callout warn" role="alert"><span>{{ sshResult.message }}</span>
            <template v-if="sshResult.fingerprint && !sshResult.changed"><br>Fingerprint <b class="mono">{{ sshResult.fingerprint }}</b></template></div>
          <div v-if="sshResult?.needs_trust"><button class="btn sm primary" :disabled="busy==='trustSsh'" @click="trustSsh"><span v-if="busy==='trustSsh'" class="spinner" />Trust this host key</button></div>
        </template>
        <template v-else>
          <div class="two"><label class="lbl">SSH host<input v-model="sshForm.host" class="field mono" placeholder="Same as the application server"></label>
            <label class="lbl">Port<input v-model="sshForm.port" class="field mono" inputmode="numeric"></label></div>
          <label class="lbl">SSH user<input v-model="sshForm.user" class="field mono" autocomplete="off"></label>
          <label class="lbl">Sign in with<select v-model="sshForm.auth" class="field"><option value="password">Password</option><option value="key">Private key</option></select></label>
          <label v-if="sshForm.auth === 'password'" class="lbl">SSH password<input v-model="sshForm.secret" class="field" type="password" autocomplete="new-password"></label>
          <label v-else class="lbl">Private key (no passphrase)<textarea v-model="sshForm.secret" class="field mono" rows="5" spellcheck="false" autocomplete="off" /></label>
          <div class="rowx"><button class="btn sm primary" :disabled="!sshForm.user || !sshForm.secret || busy==='saveSsh'" @click="saveSsh"><span v-if="busy==='saveSsh'" class="spinner" />Save SSH access</button>
            <button v-if="sshEditing" class="btn sm" @click="sshEditing = false">Cancel</button></div>
        </template>
      </template>
      <template #footer><button class="btn" @click="sel = null">Close</button><button class="btn primary" :disabled="busy==='save'" @click="save"><span v-if="busy==='save'" class="spinner" />Save details</button></template>
    </Drawer>
  </section>
</template>
