<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { get, patch, post } from '../../api'
import DataTable from '../../components/DataTable.vue'
import Drawer from '../../components/Drawer.vue'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

const users = ref<any[]>([]), sel = ref<any | null>(null), creating = ref(false), pw = ref('')
const form = ref({ username: '', password: '', role: 'user' })
const load = async () => (users.value = await get('api/users'))
async function create() {
  try { await post('api/users', form.value); creating.value = false; form.value = { username: '', password: '', role: 'user' }; await load() } catch (e) { toast(e) }
}
async function act(fn: () => Promise<unknown>) { try { await fn(); await load(); sel.value = null } catch (e) { toast(e) } }
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>Users</h1><p>Accounts are disabled, never deleted.</p></div><span class="spacer" />
      <button class="btn primary" @click="creating = true">New user</button></div>
    <DataTable clickable :rows="users" @select="sel = $event" :columns="[{key:'username',label:'Username'},{key:'role',label:'Role'},{key:'disabled',label:'Status'},{key:'created_at',label:'Created',mono:true}]">
      <template #disabled="{ row }"><StatusPill :status="row.disabled ? 'disabled' : 'active'" /></template>
    </DataTable>
    <Drawer :open="creating" title="New user" @close="creating = false">
      <label class="lbl">Username<input class="field" v-model="form.username"></label>
      <label class="lbl">Password (at least 10 characters)<input class="field" type="password" v-model="form.password"></label>
      <label class="lbl">Role<select class="field" v-model="form.role"><option>user</option><option>admin</option></select></label>
      <button class="btn primary" @click="create">Create user</button>
    </Drawer>
    <Drawer :open="!!sel" :title="sel?.username ?? ''" @close="sel = null">
      <div class="row"><StatusPill :status="sel?.disabled ? 'disabled' : 'active'" /><span class="muted">{{ sel?.role }}</span></div>
      <div class="row">
        <button class="btn" @click="act(() => patch(`api/users/${sel.id}`, { disabled: !sel.disabled }))">{{ sel?.disabled ? 'Enable account' : 'Disable account' }}</button>
        <button class="btn" @click="act(() => patch(`api/users/${sel.id}`, { role: sel.role === 'admin' ? 'user' : 'admin' }))">Make {{ sel?.role === 'admin' ? 'user' : 'admin' }}</button>
      </div>
      <label class="lbl">Reset password (they must change it at next sign-in)<input class="field" type="password" v-model="pw"></label>
      <button class="btn" :disabled="pw.length < 10" @click="act(() => post(`api/users/${sel.id}/reset-password`, { password: pw }).then(() => (pw = '')))">Reset password</button>
    </Drawer>
  </section>
</template>
