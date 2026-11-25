<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { del, get, post, put } from '../../api'
import DataTable from '../../components/DataTable.vue'
import Drawer from '../../components/Drawer.vue'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

type Member = { email: string; name: string }
const groups = ref<any[]>([]), log = ref<any[]>([]), ready = ref(true)
const sel = ref<{ id: number | null; name: string; description: string; members: Member[] } | null>(null)
const newMember = ref<Member>({ email: '', name: '' })
const testTo = ref(''), testMsg = ref('')

async function load() {
  groups.value = await get('api/email/groups'); log.value = await get('api/email/log'); ready.value = (await get('api/email/status')).ready
}
function create() { sel.value = { id: null, name: '', description: '', members: [] }; newMember.value = { email: '', name: '' } }
async function open(g: any) { sel.value = await get(`api/email/groups/${g.id}`); newMember.value = { email: '', name: '' } }
function addMember() {
  const email = newMember.value.email.trim()
  if (!email) return
  if (!sel.value!.members.some(m => m.email.toLowerCase() === email.toLowerCase())) sel.value!.members.push({ email, name: newMember.value.name.trim() })
  newMember.value = { email: '', name: '' }
}
async function save() {
  const g = sel.value!
  if (newMember.value.email.trim()) addMember()
  const body = { name: g.name, description: g.description, members: g.members }
  try { g.id ? await put(`api/email/groups/${g.id}`, body) : await post('api/email/groups', body); toast('Group saved'); sel.value = null; await load() } catch (e) { toast(e) }
}
async function remove() {
  try { await del(`api/email/groups/${sel.value!.id}`); toast('Group deleted'); sel.value = null; await load() } catch (e) { toast(e) }
}
async function sendTest() {
  testMsg.value = ''
  try { await post('api/email/test', { to: testTo.value }); testMsg.value = 'Test email sent.'; await load() } catch (e: any) { testMsg.value = e?.message ?? String(e) }
}
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="head"><div><h1>Email groups</h1><p>Groups of people who get an email when a workflow changes state. Members can be anyone with an email address, also people who have no account in Sage. Tag a group to a workflow on the Workflows page.</p></div>
      <span class="sp" /><button class="btn primary" @click="create">New group</button></div>

    <div v-if="!ready" class="callout" role="status"><span>Sending is not set up. An admin sets the mail server, the from address and <span class="mono">email.enabled</span> in the <router-link to="/admin/settings">settings</router-link>. Nothing is sent until then.</span></div>

    <DataTable clickable :rows="groups" :columns="[{key:'name',label:'Group'},{key:'description',label:'Description'},{key:'members',label:'Members',num:true},{key:'workflows',label:'Workflows',num:true}]" @select="open" />
    <p v-if="!groups.length" class="muted">No group yet.</p>

    <div class="panel" style="margin-top:20px"><div class="in">
      <h3 style="margin:0 0 6px">Send a test email</h3>
      <p class="help" style="margin:0 0 10px">Checks the mail server settings. It goes to one address and does not use a group.</p>
      <div class="rowx"><input v-model="testTo" class="field" type="email" autocomplete="email" placeholder="name@example.com" aria-label="Test email address" style="max-width:320px">
        <button class="btn" :disabled="!testTo" @click="sendTest">Send test</button></div>
      <p v-if="testMsg" class="help" role="status" style="margin:8px 0 0">{{ testMsg }}</p>
    </div></div>

    <h2 style="margin-top:24px">Recent emails</h2>
    <DataTable :rows="log" :columns="[{key:'created_at',label:'Time',mono:true},{key:'workflow',label:'Workflow',mono:true},{key:'event',label:'State'},{key:'groups',label:'Groups'},{key:'recipients',label:'People',num:true},{key:'status',label:'Result'}]">
      <template #status="{ row }"><StatusPill :status="row.status === 'sent' ? 'ok' : 'fail'" :label="row.status" /><span v-if="row.error" class="help block">{{ row.error }}</span></template>
    </DataTable>

    <Drawer :open="!!sel" :title="sel?.id ? sel.name : 'New group'" @close="sel = null">
      <template v-if="sel">
        <label class="lbl">Name<input v-model="sel.name" class="field" maxlength="60"></label>
        <label class="lbl">Description<input v-model="sel.description" class="field" maxlength="300"></label>
        <h3>Members ({{ sel.members.length }})</h3>
        <div class="callout info"><span>Emails are sent as a blind copy, so members cannot see each other. An email states only the workflow, the system, who asked and the state. It never contains results.</span></div>
        <ul v-if="sel.members.length" class="members">
          <li v-for="m in sel.members" :key="m.email"><span><b>{{ m.name || m.email }}</b><span v-if="m.name" class="help block mono">{{ m.email }}</span></span>
            <button class="btn sm ghost" :aria-label="`Remove ${m.email}`" @click="sel.members = sel.members.filter(x => x.email !== m.email)">Remove</button></li>
        </ul>
        <div class="two"><label class="lbl">Email<input v-model="newMember.email" class="field" type="email" autocomplete="off" placeholder="name@example.com" @keydown.enter.prevent="addMember"></label>
          <label class="lbl">Name (optional)<input v-model="newMember.name" class="field" autocomplete="off" @keydown.enter.prevent="addMember"></label></div>
        <div><button class="btn sm" :disabled="!newMember.email.trim()" @click="addMember">Add member</button></div>
      </template>
      <template #footer><button v-if="sel?.id" class="btn danger" @click="remove">Delete group</button><span class="sp" />
        <button class="btn" @click="sel = null">Cancel</button><button class="btn primary" :disabled="!sel?.name.trim()" @click="save">Save group</button></template>
    </Drawer>
  </section>
</template>
