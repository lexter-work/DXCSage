<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { post } from '../api'
import { loadMe } from '../session'
import { toast } from '../toast'

const router = useRouter()
const username = ref(''), password = ref(''), busy = ref(false)
async function submit() {
  busy.value = true
  try { await post('api/auth/login', { username: username.value, password: password.value }); await loadMe(); router.push('/chat') }
  catch (e: any) { toast(e.status === 429 ? 'Too many failed attempts. Try again in 15 minutes.' : 'Wrong username or password.') }
  finally { busy.value = false }
}
</script>
<template>
  <div class="login"><form class="card" @submit.prevent="submit">
    <div class="card-h"><h2>Sign in to DXC Sage</h2></div>
    <div class="card-b stack" style="display:grid;gap:12px">
      <label class="lbl">Username<input class="field" v-model="username" autocomplete="username" required></label>
      <label class="lbl">Password<input class="field" type="password" v-model="password" autocomplete="current-password" required></label>
      <button class="btn primary" :disabled="busy">Sign in</button>
    </div>
  </form></div>
</template>
