<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { post } from '../api'
import { loadMe } from '../session'
import { toast } from '../toast'
import logo from '../assets/dxc-logo.png'

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
  <div class="login">
    <div class="l">
      <img :src="logo" alt="DXC Technology">
      <div>
        <h1>SAP work, run through approved workflows.</h1>
        <p>Sage runs fixed SAP workflows on systems your admin registers. Every request, step and admin action is written to a hash-chained audit log.</p>
      </div>
      <ul>
        <li><b>RFC only</b> · no SSH, no database clients</li>
        <li><b>Read-only health checks</b> before any workflow runs</li>
        <li><b>Claude or GPT</b> · keys held encrypted on the server</li>
      </ul>
    </div>
    <div class="r">
      <form @submit.prevent="submit">
        <h2>Sign in to Sage</h2>
        <p>Use the local account your admin created.</p>
        <label class="lbl">Username<input v-model="username" class="field" autocomplete="username" required></label>
        <label class="lbl">Password<input v-model="password" class="field" type="password" autocomplete="current-password" required></label>
        <button class="btn primary" :disabled="busy">Sign in</button>
        <span class="muted" style="font-size:12px">Too many failed attempts lock sign-in for 15 minutes.</span>
      </form>
    </div>
  </div>
</template>
