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
    <div class="head"><div><h1>Account</h1><p>{{ session.user?.username }} · {{ session.user?.role }}</p></div></div>
    <div v-if="session.user?.must_change_password" class="callout" style="max-width:420px;margin-bottom:18px"><span><b>Change your password to continue.</b> This shows on first sign-in and after an admin resets your password.</span></div>
    <form class="form" @submit.prevent="submit">
      <label class="lbl">Current password<input v-model="old" class="field" type="password" autocomplete="current-password" required></label>
      <label class="lbl">New password (at least 10 characters)<input v-model="nw" class="field" type="password" minlength="10" autocomplete="new-password" required></label>
      <div><button class="btn primary">Change password</button></div>
    </form>
  </section>
</template>
