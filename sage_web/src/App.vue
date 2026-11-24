<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { post } from './api'
import { session } from './session'
import { toastState } from './toast'
import { getMode, setMode } from './theme'
import { layout, toggleNav } from './layout'
import Icon from './components/Icon.vue'
import logo from './assets/dxc-logo.png'

const route = useRoute(), router = useRouter()
const modes = ['light', 'dark', 'system'] as const
const mode = ref(getMode())
const pick = (m: (typeof modes)[number]) => { mode.value = m; setMode(m) }
async function logout() { await post('api/auth/logout'); session.user = null; router.push('/login') }

const work = [['/chat', 'Chat', 'chat'], ['/usage', 'My usage', 'usage']]
const admin = [
  ['/admin/systems', 'Systems', 'systems'], ['/admin/workflows', 'Workflows', 'workflows'], ['/admin/health', 'Health', 'health'],
  ['/admin/runs', 'Runs', 'runs'], ['/admin/usage', 'Usage (all)', 'usage'], ['/admin/audit', 'Audit', 'audit'],
  ['/admin/users', 'Users', 'users'], ['/admin/settings', 'Settings', 'settings'],
]
const here = (to: string) => route.path === to || route.path.startsWith(to + '/')
const crumb = computed(() => {
  const all = [...work.map(w => ['Work', w[0], w[1]]), ...admin.map(a => ['Admin', a[0], a[1]])]
  const hit = all.find(([, to]) => here(to))
  if (hit) return [hit[0], hit[2], ...(route.path.startsWith('/admin/workflows/') ? ['Setup guide'] : [])]
  return route.path === '/account' ? ['Account'] : []
})
const initials = computed(() => (session.user?.username ?? '').slice(0, 2).toUpperCase())
const bare = computed(() => !session.user)
</script>

<template>
  <header class="bar">
    <img class="logo" :src="logo" alt="DXC Technology">
    <span class="div" aria-hidden="true" />
    <span class="product">Sage</span>
    <span v-if="!bare" class="ctx"><template v-for="(c, i) in crumb" :key="i"><span v-if="i">·</span><b v-if="i === crumb.length - 1">{{ c }}</b><span v-else>{{ c }}</span></template></span>
    <span class="sp" />
    <div class="seg" role="group" aria-label="Theme">
      <button v-for="m in modes" :key="m" :aria-pressed="mode === m" @click="pick(m)">{{ m.charAt(0).toUpperCase() + m.slice(1) }}</button>
    </div>
    <div v-if="!bare" class="who"><span class="avatar" aria-hidden="true">{{ initials }}</span><span class="nm">{{ session.user?.username }}<small>{{ session.user?.role === 'admin' ? 'Admin' : 'User' }}</small></span></div>
  </header>

  <router-view v-if="bare" />
  <div v-else class="shell" :class="{ navc: layout.navCollapsed }">
    <nav id="sidenav" class="side" aria-label="Main">
      <div class="nlabel">Work</div>
      <a v-for="[to, label, icon] in work" :key="to" class="nav" :href="'#' + to" :title="label"
         :aria-current="here(to) ? 'page' : undefined" @click.prevent="router.push(to)"><Icon :name="icon" /><span class="nl">{{ label }}</span></a>
      <template v-if="session.user?.role === 'admin'">
        <div class="nlabel">Admin</div>
        <a v-for="[to, label, icon] in admin" :key="to" class="nav" :href="'#' + to" :title="label"
           :aria-current="here(to) ? 'page' : undefined" @click.prevent="router.push(to)"><Icon :name="icon" /><span class="nl">{{ label }}</span></a>
      </template>
      <div class="foot">
        <button class="nav tg navtg" :aria-expanded="!layout.navCollapsed" aria-controls="sidenav"
                :title="layout.navCollapsed ? 'Expand menu (Ctrl+B)' : 'Collapse menu (Ctrl+B)'" @click="toggleNav">
          <Icon :name="layout.navCollapsed ? 'expand' : 'collapse'" /><span class="nl">{{ layout.navCollapsed ? 'Expand menu' : 'Collapse menu' }}</span>
        </button>
        <a class="nav" href="#/account" title="Account" :aria-current="route.path === '/account' ? 'page' : undefined"
           @click.prevent="router.push('/account')"><Icon name="account" /><span class="nl">Account</span></a>
        <button class="nav" title="Sign out" @click="logout"><Icon name="logout" /><span class="nl">Sign out</span></button>
      </div>
    </nav>
    <main><router-view /></main>
  </div>
  <div class="toast" :class="{ show: toastState.show }" role="status">{{ toastState.text }}</div>
</template>
