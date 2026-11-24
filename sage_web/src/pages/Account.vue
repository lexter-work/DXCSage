<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { post } from '../api'
import { loadMe, session } from '../session'
import { toast } from '../toast'

const router = useRouter()
const old = ref(''), nw = ref('')
async function submit() {
  try { await post('api/auth/change-password', { old: old.value, new: nw.value }); await loadMe(); toast('Password changed'); router.push('/chat') }
  catch (e) { toast(e) }
}
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>Account</h1><p>{{ session.user?.username }} · {{ session.user?.role }}</p></div></div>
    <div v-if="session.user?.must_change_password" class="callout"><b>Change your password to continue.</b></div>
    <form class="card" style="max-width:420px;margin-top:14px" @submit.prevent="submit"><div class="card-b" style="display:grid;gap:12px">
      <label class="lbl">Current password<input class="field" type="password" v-model="old" required></label>
      <label class="lbl">New password (at least 10 characters)<input class="field" type="password" v-model="nw" minlength="10" required></label>
      <button class="btn primary">Change password</button>
    </div></form>
  </section>
</template>
