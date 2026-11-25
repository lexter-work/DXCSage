<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { get, patch, post } from '../../api'
import DataTable from '../../components/DataTable.vue'
import Drawer from '../../components/Drawer.vue'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

const users = ref<any[]>([]), sel = ref<any | null>(null), creating = ref(false), pw = ref(''), busy = ref<string | null>(null)
const form = ref({ username: '', password: '', role: 'user' })
const load = async () => (users.value = await get('api/users'))
async function create() {
  busy.value = 'create'
  try { await post('api/users', form.value); creating.value = false; form.value = { username: '', password: '', role: 'user' }; await load(); toast('User created') }
  catch (e) { toast(e) }
  finally { busy.value = null }
}
async function act(key: string, fn: () => Promise<unknown>) {
  busy.value = key
  try { await fn(); await load(); sel.value = null } catch (e) { toast(e) } finally { busy.value = null }
}
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="head"><div><h1>Users</h1><p>Local accounts. Accounts are disabled, never deleted.</p></div><span class="sp" />
      <button class="btn primary" @click="creating = true">New user</button></div>
    <DataTable clickable :rows="users" :columns="[{key:'username',label:'Username'},{key:'role',label:'Role'},{key:'disabled',label:'Status'},{key:'created_at',label:'Created',mono:true}]" @select="sel = $event">
      <template #role="{ row }"><span class="role" :class="row.role">{{ row.role }}</span></template>
      <template #disabled="{ row }"><StatusPill :status="row.disabled ? 'disabled' : 'active'" /></template>
      <template #created_at="{ row }">{{ row.created_at.slice(0, 16).replace('T', ' ') }}</template>
    </DataTable>

    <Drawer :open="creating" title="New user" @close="creating = false">
      <label class="lbl">Username<input v-model="form.username" class="field" autocomplete="off"></label>
      <label class="lbl">Password (at least 10 characters)<input v-model="form.password" class="field" type="password" autocomplete="new-password"></label>
      <label class="lbl">Role<select v-model="form.role" class="field"><option>user</option><option>admin</option></select></label>
      <div class="callout info"><span>They must change this password at first sign-in.</span></div>
      <template #footer><button class="btn" @click="creating = false">Cancel</button><button class="btn primary" :disabled="busy==='create'" @click="create"><span v-if="busy==='create'" class="spinner" />Create user</button></template>
    </Drawer>

    <Drawer :open="!!sel" :title="sel?.username ?? ''" @close="sel = null">
      <template #status><StatusPill :status="sel?.disabled ? 'disabled' : 'active'" /></template>
      <div class="muted">Role: {{ sel?.role }}</div>
      <div class="rowx">
        <button class="btn sm" :disabled="busy==='toggle'" @click="act('toggle', () => patch(`api/users/${sel.id}`, { disabled: !sel.disabled }))"><span v-if="busy==='toggle'" class="spinner" />{{ sel?.disabled ? 'Enable account' : 'Disable account' }}</button>
        <button class="btn sm" :disabled="busy==='role'" @click="act('role', () => patch(`api/users/${sel.id}`, { role: sel.role === 'admin' ? 'user' : 'admin' }))"><span v-if="busy==='role'" class="spinner" />Make {{ sel?.role === 'admin' ? 'user' : 'admin' }}</button>
      </div>
      <h3>Reset password</h3>
      <label class="lbl">New password (they must change it at next sign-in)<input v-model="pw" class="field" type="password" placeholder="At least 10 characters" autocomplete="new-password"></label>
      <div><button class="btn sm" :disabled="pw.length < 10 || busy==='reset'" @click="act('reset', () => post(`api/users/${sel.id}/reset-password`, { password: pw }).then(() => (pw = '')))"><span v-if="busy==='reset'" class="spinner" />Reset password</button></div>
      <div class="callout info"><span>Disabled accounts can't sign in. Their chats, runs and audit entries are kept.</span></div>
      <template #footer><button class="btn" @click="sel = null">Close</button></template>
    </Drawer>
  </section>
</template>
