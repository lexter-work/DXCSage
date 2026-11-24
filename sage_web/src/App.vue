<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { post } from './api'
import { session } from './session'
import { toastState } from './toast'
import { getMode, setMode } from './theme'

const route = useRoute(), router = useRouter()
const bare = computed(() => !session.user || route.path === '/login')
const mode = ref(getMode())
const pick = (m: 'light' | 'dark' | 'system') => { mode.value = m; setMode(m) }
async function logout() { await post('api/auth/logout'); session.user = null; router.push('/login') }
const adminLinks = [
  ['/admin/systems', 'Systems'], ['/admin/workflows', 'Workflows'], ['/admin/health', 'Health'], ['/admin/runs', 'Runs'],
  ['/admin/audit', 'Audit'], ['/admin/usage', 'Usage (all)'], ['/admin/users', 'Users'], ['/admin/settings', 'Settings'],
]
</script>

<template>
  <router-view v-if="bare" />
  <div v-else class="app">
    <aside>
      <div class="brand"><div class="brand-mark">S</div><div><b>DXC Sage</b><small>{{ session.user?.username }}</small></div></div>
      <div class="nav-label">Work</div>
      <router-link class="nav" to="/chat"><span class="nl">Chat</span></router-link>
      <router-link class="nav" to="/usage"><span class="nl">My usage</span></router-link>
      <template v-if="session.user?.role === 'admin'">
        <div class="nav-label">Admin</div>
        <router-link v-for="[to, label] in adminLinks" :key="to" class="nav" :to="to"><span class="nl">{{ label }}</span></router-link>
      </template>
      <div class="side-foot">
        <div class="seg" role="group" aria-label="Theme">
          <button v-for="m in (['light', 'dark', 'system'] as const)" :key="m" :aria-pressed="mode === m" @click="pick(m)">{{ m }}</button>
        </div>
        <router-link class="nav" to="/account"><span class="nl">Account</span></router-link>
        <button class="nav" @click="logout"><span class="nl">Sign out</span></button>
      </div>
    </aside>
    <main><router-view /></main>
  </div>
  <div class="toast" :class="{ show: toastState.show }" role="status">{{ toastState.text }}</div>
</template>
