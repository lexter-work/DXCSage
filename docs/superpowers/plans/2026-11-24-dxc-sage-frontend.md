# DXC Sage Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, one pass). Workspace pace rules in `D:\User\Documents\Programming\AGENTS.md` override skill ceremony: no baseline run, no worktree, no branch, no subagent review. Each task runs only its own check, once. One commit at the end. Run this plan after the backend plan.

**Goal:** Build `sage_web`, the Vue 3 frontend of DXC Sage: login, streaming chat with workflow cards, usage, and the admin pages (users, systems, workflows with setup guide, health matrix, settings, runs, audit, usage).

**Architecture:** Single-page app talking only to `sage_api` through relative URLs (`api/...`, hash routing), so it works behind ServiceHub's `/s/<id>/` proxy. Styled with the `grey-console-frontend` skill (neutral grey, ember orange accent, Light/Dark/System). Admin actions open in a drawer; only the chat-delete confirmation is a modal. The chat view is rebuilt from stored messages plus replayed run events, so a reload or reconnect shows a still-running or waiting run.

**Tech Stack:** Vue 3 (`<script setup lang="ts">`), vue-router 4, Vite 5, TypeScript, vue-tsc, vitest, pnpm; nginx for the container.

**Spec:** `Applications/DXCSage/docs/superpowers/specs/2026-11-24-dxc-sage-design.md`. API contract: `2026-11-24-dxc-sage-backend.md`, Tasks 3, 5, 7, 10, 11.

## Global Constraints

- Use `pnpm` (never npm). Project root `Applications/DXCSage/sage_web/`. Dev port 29701; proxy `/api` to `http://localhost:29700`.
- Relative URLs only: write `api/chats`, never `/api/chats`. `base: './'` in Vite. Hash router (`createWebHashHistory`).
- Style from `.agents/skills/grey-console-frontend/` (`references/base.css` copied in unchanged). Colors only through its tokens. No gradients, no glow. Sentence case. No corporate logos or colors; the app name text "DXC Sage" is fine.
- No reduced-motion handling, no `prefers-reduced-motion` query.
- Drawers for admin interactions; `ConfirmModal` only for deleting a chat.
- Secrets are write-only: never display a password or API key; show "set" or "not set".
- Status always has a word, never color alone (`StatusPill`).
- Not run in this plan: Docker build of the web image. The container files are written but not built.

## File Structure

```
sage_web/
  package.json tsconfig.json vite.config.ts index.html Dockerfile nginx.conf
  src/
    main.ts App.vue router.ts api.ts session.ts theme.ts toast.ts layout.ts messages.ts messages.test.ts
    styles/{base.css,app.css}
    components/{Drawer.vue,ConfirmModal.vue,StatusPill.vue,DataTable.vue,Icon.vue}
    assets/dxc-logo.png
    pages/{Login.vue,Account.vue,Chat.vue,MyUsage.vue}
    pages/admin/{Users.vue,Systems.vue,Workflows.vue,WorkflowSetup.vue,Health.vue,Settings.vue,Runs.vue,Audit.vue,Usage.vue}
```

---

### Task 1: Scaffold, shell, auth pages

**Files:**
- Create: everything in `sage_web/` except `pages/Chat.vue`, `messages*`, `pages/MyUsage.vue`, `pages/admin/*`, `Dockerfile`, `nginx.conf` (later tasks). Router imports them lazily, so they can be added after.

**Interfaces:**
- Produces: `api<T>(method, path, body?)`, `get`, `post`, `put`, `patch`, `del` (all relative paths, throw `ApiError(status, detail)`); `session` (`{user, loaded}`), `loadMe()`; `toast(msg)`; `theme.setMode('light'|'dark'|'system')`; components `Drawer` (props `open`, `title`; emits `close`), `ConfirmModal` (props `open`, `title`, `text`, `confirmLabel`; emits `confirm`, `cancel`), `StatusPill` (prop `status`), `DataTable` (props `columns: {key,label,mono?}[]`, `rows`, `clickable?`; emits `select`; slots per column key).

- [ ] **Step 1: Create the project files**

`sage_web/package.json`:
```json
{
  "name": "sage-web", "private": true, "version": "0.1.0", "type": "module",
  "scripts": { "dev": "vite", "build": "vue-tsc --noEmit && vite build", "test": "vitest run" },
  "dependencies": { "vue": "^3.5.0", "vue-router": "^4.4.0" },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.1.0", "typescript": "^5.5.0", "vite": "^5.4.0",
    "vitest": "^2.1.0", "vue-tsc": "^2.1.0"
  }
}
```

`sage_web/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022", "module": "ESNext", "moduleResolution": "bundler", "strict": true,
    "jsx": "preserve", "skipLibCheck": true, "noEmit": true, "types": ["vite/client"], "lib": ["ES2022", "DOM", "DOM.Iterable"]
  },
  "include": ["src/**/*.ts", "src/**/*.vue"]
}
```

`sage_web/vite.config.ts`:
```ts
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: './',
  plugins: [vue()],
  server: { port: 29701, proxy: { '/api': 'http://localhost:29700' } },
  test: { environment: 'node' },
})
```

`sage_web/index.html`:
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DXC Sage</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="./src/main.ts"></script>
</body>
</html>
```

Copy the style base (PowerShell):
```powershell
cd D:\User\Documents\Programming\Applications\DXCSage\sage_web
New-Item -ItemType Directory -Force src\styles | Out-Null
Copy-Item ..\..\..\.agents\skills\grey-console-frontend\references\base.css src\stylesase.css
```

`src/styles/app.css` (additions on top of the skill's `base.css`; tokens only):
```css
.card table { width: 100%; border-collapse: collapse; }
.card th, .card td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--line); font-size: 13px; vertical-align: top; }
.card th { color: var(--ink-3); font-weight: 500; font-size: 12px; }
.card tr.click { cursor: pointer; } .card tr.click:hover { background: var(--hover); }
.mono { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.sdrawer-bg { position: fixed; inset: 0; background: rgba(20, 20, 15, .35); display: flex; justify-content: flex-end; z-index: 50; }
.sdrawer { width: min(520px, 100%); height: 100%; background: var(--panel); border-left: 1px solid var(--line); display: flex; flex-direction: column; }
.sdrawer header { display: flex; align-items: center; gap: 10px; padding: 16px 18px; border-bottom: 1px solid var(--line); }
.sdrawer header h2 { margin: 0; font-size: 15px; flex: 1; }
.sdrawer .sbody { padding: 16px 18px; overflow: auto; display: grid; gap: 12px; align-content: start; }
.modal-bg { position: fixed; inset: 0; background: rgba(20, 20, 15, .35); display: grid; place-items: center; z-index: 60; }
.modal { background: var(--panel); border: 1px solid var(--line); border-radius: var(--r-lg); padding: 18px; width: min(420px, 92vw); box-shadow: var(--shadow); }
.lbl { display: grid; gap: 4px; font-size: 12.5px; color: var(--ink-2); }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.login { min-height: 100vh; display: grid; place-items: center; padding: 16px; }
.login .card { width: min(380px, 100%); }
.chat-main { display: flex; flex-direction: column; gap: 12px; }
.msgs { display: grid; gap: 10px; align-content: start; min-height: 40vh; }
.bubble { padding: 10px 12px; border-radius: var(--r-md); white-space: pre-wrap; max-width: 80ch; }
.bubble.user { background: var(--accent-soft); justify-self: end; }
.bubble.assistant { background: var(--panel); border: 1px solid var(--line); }
.toolcard { border: 1px solid var(--line); border-radius: var(--r-md); background: var(--panel); padding: 10px 12px; max-width: 80ch; }
.toolcard pre, pre.out { background: var(--sunken); padding: 8px 10px; border-radius: var(--r-sm); overflow: auto; font: 12px/1.45 var(--mono); margin: 6px 0 0; white-space: pre-wrap; }
.matrix td, .matrix th { text-align: center; }
@media (max-width: 760px) { .page { padding: 16px 16px 40px; } }
```

- [ ] **Step 2: Write core modules**

`src/api.ts`:
```ts
export class ApiError extends Error {
  constructor(public status: number, public detail: string) { super(detail) }
}

let onUnauthorized: () => void = () => {}
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn }

export async function api<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method, credentials: 'same-origin',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (r.status === 401 && !path.startsWith('api/auth/login')) onUnauthorized()
  if (!r.ok) {
    let detail = r.statusText
    try { const j = await r.json(); detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* keep statusText */ }
    throw new ApiError(r.status, detail)
  }
  return ((r.headers.get('content-type') ?? '').includes('json') ? r.json() : r.text()) as Promise<T>
}
export const get = <T = any>(p: string) => api<T>('GET', p)
export const post = <T = any>(p: string, b?: unknown) => api<T>('POST', p, b ?? {})
export const put = <T = any>(p: string, b?: unknown) => api<T>('PUT', p, b ?? {})
export const patch = <T = any>(p: string, b?: unknown) => api<T>('PATCH', p, b ?? {})
export const del = <T = any>(p: string) => api<T>('DELETE', p)
```

`src/session.ts`:
```ts
import { reactive } from 'vue'
import { get } from './api'

export interface Me { id: number; username: string; role: string; must_change_password: boolean }
export const session = reactive<{ user: Me | null; loaded: boolean }>({ user: null, loaded: false })

export async function loadMe() {
  try { session.user = await get<Me>('api/auth/me') } catch { session.user = null }
  session.loaded = true
}
```

`src/toast.ts`:
```ts
import { reactive } from 'vue'
import { ApiError } from './api'

export const toastState = reactive({ text: '', show: false })
let timer: number | undefined
export function toast(msg: unknown) {
  toastState.text = msg instanceof ApiError ? msg.detail : msg instanceof Error ? msg.message : String(msg)
  toastState.show = true
  clearTimeout(timer)
  timer = window.setTimeout(() => (toastState.show = false), 4000)
}
```

`src/theme.ts`:
```ts
type Mode = 'light' | 'dark' | 'system'
const KEY = 'sage.theme'
const mq = window.matchMedia('(prefers-color-scheme: dark)')

function apply(mode: Mode) {
  document.documentElement.dataset.theme = mode === 'system' ? (mq.matches ? 'dark' : 'light') : mode
}
export function getMode(): Mode {
  try { return (localStorage.getItem(KEY) as Mode) || 'system' } catch { return 'system' }
}
export function setMode(mode: Mode) {
  try { localStorage.setItem(KEY, mode) } catch { /* private window: keep in memory only */ }
  apply(mode)
}
export function initTheme() {
  apply(getMode())
  mq.addEventListener('change', () => getMode() === 'system' && apply('system'))
}
```

`src/router.ts`:
```ts
import { createRouter, createWebHashHistory } from 'vue-router'
import { loadMe, session } from './session'

const admin = { admin: true }
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', component: () => import('./pages/Login.vue'), meta: { public: true } },
    { path: '/account', component: () => import('./pages/Account.vue') },
    { path: '/', redirect: '/chat' },
    { path: '/chat', component: () => import('./pages/Chat.vue') },
    { path: '/usage', component: () => import('./pages/MyUsage.vue') },
    { path: '/admin/users', component: () => import('./pages/admin/Users.vue'), meta: admin },
    { path: '/admin/systems', component: () => import('./pages/admin/Systems.vue'), meta: admin },
    { path: '/admin/workflows', component: () => import('./pages/admin/Workflows.vue'), meta: admin },
    { path: '/admin/workflows/:name/:systemId', component: () => import('./pages/admin/WorkflowSetup.vue'), meta: admin },
    { path: '/admin/health', component: () => import('./pages/admin/Health.vue'), meta: admin },
    { path: '/admin/runs', component: () => import('./pages/admin/Runs.vue'), meta: admin },
    { path: '/admin/audit', component: () => import('./pages/admin/Audit.vue'), meta: admin },
    { path: '/admin/usage', component: () => import('./pages/admin/Usage.vue'), meta: admin },
    { path: '/admin/settings', component: () => import('./pages/admin/Settings.vue'), meta: admin },
  ],
})

router.beforeEach(async (to) => {
  if (!session.loaded) await loadMe()
  if (!session.user) return to.meta.public ? true : '/login'
  if (to.path === '/login') return '/chat'
  if (session.user.must_change_password && to.path !== '/account') return '/account'
  if (to.meta.admin && session.user.role !== 'admin') return '/chat'
  return true
})
```

`src/main.ts`:
```ts
import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import { setUnauthorizedHandler } from './api'
import { session } from './session'
import { initTheme } from './theme'
import { initShortcuts } from './layout'
import './styles/base.css'
import './styles/app.css'

initTheme()
initShortcuts()
setUnauthorizedHandler(() => { session.user = null; router.push('/login') })
createApp(App).use(router).mount('#app')
```

- [ ] **Step 3: Write components**

`src/components/StatusPill.vue`:
```vue
<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ status: string | null | undefined }>()
const cls = computed(() => {
  const s = props.status ?? ''
  if (['pass', 'ok', 'enabled', 'active', 'done'].includes(s)) return 'ok'
  if (['warn', 'waiting', 'setup', 'running', 'inactive', 'unknown'].includes(s)) return 'warn'
  if (['fail', 'failed', 'blocked', 'error', 'disabled', 'cancelled'].includes(s)) return 'bad'
  return 'off'
})
</script>
<template><span class="pill" :class="cls">{{ status || 'not set up' }}</span></template>
```

`src/components/Drawer.vue`:
```vue
<script setup lang="ts">
defineProps<{ open: boolean; title: string }>()
defineEmits<{ close: [] }>()
</script>
<template>
  <Teleport to="body">
    <div v-if="open" class="sdrawer-bg" @click.self="$emit('close')">
      <div class="sdrawer" role="dialog" aria-modal="true" :aria-label="title">
        <header><h2>{{ title }}</h2><button class="btn ghost sm" @click="$emit('close')">Close</button></header>
        <div class="sbody"><slot /></div>
      </div>
    </div>
  </Teleport>
</template>
```

`src/components/ConfirmModal.vue`:
```vue
<script setup lang="ts">
defineProps<{ open: boolean; title: string; text: string; confirmLabel: string }>()
defineEmits<{ confirm: []; cancel: [] }>()
</script>
<template>
  <Teleport to="body">
    <div v-if="open" class="modal-bg" @click.self="$emit('cancel')">
      <div class="modal" role="alertdialog" aria-modal="true">
        <h2 style="margin:0 0 8px;font-size:15px">{{ title }}</h2>
        <p class="muted" style="margin:0 0 16px">{{ text }}</p>
        <div class="row" style="justify-content:flex-end">
          <button class="btn" @click="$emit('cancel')">Cancel</button>
          <button class="btn danger" @click="$emit('confirm')">{{ confirmLabel }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
```

`src/components/DataTable.vue`:
```vue
<script setup lang="ts">
defineProps<{ columns: { key: string; label: string; mono?: boolean }[]; rows: any[]; clickable?: boolean }>()
defineEmits<{ select: [row: any] }>()
</script>
<template>
  <div class="card"><div class="tablewrap"><table>
    <thead><tr><th v-for="c in columns" :key="c.key">{{ c.label }}</th></tr></thead>
    <tbody>
      <tr v-for="(r, i) in rows" :key="r.id ?? i" :class="{ click: clickable }" @click="clickable && $emit('select', r)">
        <td v-for="c in columns" :key="c.key" :class="{ mono: c.mono }"><slot :name="c.key" :row="r">{{ r[c.key] }}</slot></td>
      </tr>
      <tr v-if="!rows.length"><td :colspan="columns.length" class="muted">Nothing here yet.</td></tr>
    </tbody>
  </table></div></div>
</template>
```

- [ ] **Step 3b: Shell state, icons and sidebar CSS**

`src/layout.ts`:
```ts
import { reactive } from 'vue'

// Remembered per browser; the app works when storage is blocked.
const store = {
  get(k: string) { try { return localStorage.getItem(k) } catch { return null } },
  set(k: string, v: string) { try { localStorage.setItem(k, v) } catch { /* keep in memory */ } },
}

export const layout = reactive({
  navCollapsed: store.get('sage.navCollapsed') === '1',
  threadsCollapsed: store.get('sage.threadsCollapsed') === '1',
})

export function toggleNav() { layout.navCollapsed = !layout.navCollapsed; store.set('sage.navCollapsed', layout.navCollapsed ? '1' : '0') }
export function setThreadsCollapsed(c: boolean) { layout.threadsCollapsed = c; store.set('sage.threadsCollapsed', c ? '1' : '0') }
export function toggleThreads() { setThreadsCollapsed(!layout.threadsCollapsed) }

/** Ctrl+B toggles the main menu, Ctrl+Shift+B the chat list. */
export function initShortcuts() {
  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
      e.preventDefault()
      e.shiftKey ? toggleThreads() : toggleNav()
    }
  })
}
```
`main.ts` calls `initShortcuts()` after `initTheme()`.

`src/components/Icon.vue` (outline icons, one stroke weight; names used: chat, usage, systems, workflows, health, runs, audit, users, settings, account, logout, collapse, expand, plus, close, check, alert, chev, help, trash):
```vue
<script setup lang="ts">
// Drawn outline icons, one stroke weight (set in .i). Static strings only, so v-html is safe here.
const P: Record<string, string> = {
  chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
  usage: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  systems: '<rect x="3" y="4" width="18" height="7" rx="1"/><rect x="3" y="13" width="18" height="7" rx="1"/><path d="M7 7.5h.01M7 16.5h.01"/>',
  workflows: '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.5 6H15a3 3 0 0 1 0 6H9a3 3 0 0 0 0 6h6.5"/>',
  health: '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
  runs: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  audit: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 7 19.4l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 3 13.7H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 10.3 3V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 1.2 2.9H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  account: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  logout: '<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3"/>',
  collapse: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M16 15l-3-3 3-3"/>',
  expand: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M14 9l3 3-3 3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  check: '<path d="M5 12l5 5L20 7"/>',
  alert: '<path d="M12 7v6M12 17h.01"/>',
  chev: '<path d="M9 6l6 6-6 6"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.6a2.5 2.5 0 0 1 4.9.7c0 1.6-2.4 2-2.4 3.5M12 17h.01"/>',
  trash:'<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
}
defineProps<{ name: string }>()
</script>
<template><svg class="i" viewBox="0 0 24 24" aria-hidden="true" v-html="P[name]" /></template>
```
Add `.i{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;flex:none}` to `app.css`. Put the DXC logo at `src/assets/dxc-logo.png` (bundled, no remote image).

Add the shell CSS to `app.css` (tokens only; `--header`, `--header-line`, `--canvas` are the top-bar tokens, grey in both themes). The built `sage_web/src/styles/dxc.css` holds the full version:
```css
.bar{height:56px;display:flex;align-items:center;gap:14px;padding:0 16px;background:var(--header);color:var(--canvas);border-bottom:1px solid var(--header-line);position:sticky;top:0;z-index:20}
.shell{display:grid;grid-template-columns:auto minmax(0,1fr);min-height:calc(100vh - 56px)}
nav.side{width:216px;position:sticky;top:56px;height:calc(100vh - 56px);align-self:start;overflow:hidden auto;white-space:nowrap;border-right:1px solid var(--line);background:var(--panel);padding:16px 10px;display:flex;flex-direction:column;gap:2px}
.shell.navc nav.side{width:60px;padding-left:8px;padding-right:8px}
.shell.navc .nl,.shell.navc .count{display:none}
.shell.navc .nav{justify-content:center;padding:8px 0}
.side .foot{margin-top:auto;border-top:1px solid var(--line);padding-top:10px}
.nav{position:relative}
.nav[aria-current="page"]{background:var(--accent-soft);color:var(--accent);font-weight:600}
.nav[aria-current="page"]::before{content:"";position:absolute;left:-10px;top:6px;bottom:6px;width:3px;background:var(--accent);border-radius:0 2px 2px 0}
.iconbtn{width:30px;height:30px;display:grid;place-items:center;border:1px solid transparent;border-radius:4px;background:none;cursor:pointer;color:var(--ink-2);flex:none}
.chat{display:grid;grid-template-columns:var(--th-w,296px) minmax(0,1fr);height:calc(100vh - 56px)}
.chat.thc{--th-w:56px}
.threads{display:flex;flex-direction:column;min-width:0;overflow:hidden;border-right:1px solid var(--line);background:var(--bg)}
.thbar{display:flex;align-items:center;gap:8px;padding:12px 12px 0 16px}
.thbar .ttl{font-weight:600;font-size:13px;margin-right:auto;white-space:nowrap}
.rail{display:none;flex-direction:column;align-items:center;gap:6px;padding:10px 0}
.rail .rt{width:36px;height:30px;display:grid;place-items:center;border:0;border-radius:4px;background:none;cursor:pointer}
.rail .rt[aria-current="true"]{background:var(--panel);box-shadow:inset 3px 0 0 var(--accent)}
.chat.thc .top,.chat.thc .tlist,.chat.thc .thbar .ttl{display:none}
.chat.thc .thbar{justify-content:center;padding:12px 0 0}
.chat.thc .rail{display:flex}
.chatsbtn,.thclose,.thscrim{display:none}
@media (max-width:1000px){
  .shell,.shell.navc{grid-template-columns:60px minmax(0,1fr)}
  nav.side,.shell.navc nav.side{width:60px;padding:16px 8px}
  nav.side .nl,nav.side .count{display:none}
  nav.side .nav{justify-content:center;padding:8px 0}
  .navtg,.thtg{display:none}
  .chat{grid-template-columns:minmax(0,1fr)}
  .threads{position:fixed;top:56px;left:0;bottom:0;width:min(320px,86vw);z-index:36;transform:translateX(-100%);visibility:hidden}
  .chat.thopen .threads{transform:none;visibility:visible}
  .chat.thopen .thscrim{display:block;position:fixed;inset:56px 0 0 0;background:rgb(0 0 0 / .5);z-index:35}
  .chatsbtn,.thclose{display:inline-flex}
  .chat.thc .top,.chat.thc .tlist{display:block}
  .chat.thc .rail{display:none}
}
```

- [ ] **Step 4: Write the shell and auth pages**

`src/App.vue`:
```vue
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
```
**Shell rules (both sidebars are required):**
- 56px top bar (`.bar`): logo, divider, product name, breadcrumb, theme switch, user.
- Main menu (`nav.side`): 216px with labels, or a 60px icon-only strip (`.shell.navc`). Collapse button at the bottom and **Ctrl+B**. State remembered (`layout.ts`). Every item has an icon and a `title` tooltip.
- Chat list (Chat page, `.threads`): 296px, or a 56px rail with a "+" button and one status dot per chat (`.chat.thc`). Collapse button in its header and **Ctrl+Shift+B**. State remembered.
- 1000px and below: the main menu stays a **60px icon-only left sidebar** (no tab row, no expand control, labels only as tooltips). The chat list becomes a 320px slide-in drawer opened by a "Chats" button, with scrim, Esc to close, and focus moved in and back.
- No blue surfaces: grey panels; blue only for text, icons, the active-item bar and focus rings.

`src/pages/Login.vue`:
```vue
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
```

`src/pages/Account.vue`:
```vue
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
```

- [ ] **Step 5: Install and check**

Run: `cd sage_web; pnpm install; pnpm exec vue-tsc --noEmit`
Expected: type check passes. (Pages added in later tasks are imported lazily as strings of paths; `vue-tsc` will report missing modules until Tasks 2 and 3 exist, so run the type check again at the end of Task 3 and only fix errors from the files you wrote.) If vue-tsc reports "Cannot find module './pages/Chat.vue'", that is expected now.

---

### Task 2: Messages model, tests, Chat page, My usage

**Files:**
- Create: `src/messages.ts`, `src/messages.test.ts`, `src/pages/Chat.vue`, `src/pages/MyUsage.vue`

**Interfaces:**
- Produces: `Msg`, `Item`, `buildItems(messages: Msg[], hideRunId?: number | null): Item[]`, `applyEvent(items: Item[], ev: {type: string; data: any}): void`. Consumes backend routes `GET api/chats`, `POST api/chats`, `PATCH api/chats/{id}`, `DELETE api/chats/{id}`, `GET api/chats/{id}/messages`, `POST api/chats/{id}/runs`, `POST api/runs/{id}/cancel`, `GET api/runs/{id}/events?after=N` (SSE), `GET api/providers`, `GET api/usage/me`.

- [ ] **Step 1: Write the failing test** — `src/messages.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import { applyEvent, buildItems, type Item, type Msg } from './messages'

const msg = (id: number, run_id: number | null, role: 'user' | 'assistant', content: unknown[]): Msg =>
  ({ id, run_id, role, content: JSON.stringify(content) })

const history: Msg[] = [
  msg(1, 1, 'user', [{ type: 'text', text: 'check TS3' }]),
  msg(2, 1, 'assistant', [{ type: 'text', text: 'on it' }, { type: 'tool_use', id: 'c1', name: 'wf', input: { system_name: 'TS3' } }]),
  msg(3, 1, 'user', [{ type: 'tool_result', tool_use_id: 'c1', content: '{"ok":1}', is_error: false }]),
  msg(4, 1, 'assistant', [{ type: 'text', text: 'done' }]),
]

describe('buildItems', () => {
  it('turns stored blocks into chat items and attaches tool results', () => {
    const items = buildItems(history)
    expect(items.map(i => i.kind)).toEqual(['user', 'assistant', 'tool', 'assistant'])
    const tool = items[2] as Extract<Item, { kind: 'tool' }>
    expect(tool.status).toBe('ok')
    expect(tool.output).toBe('{"ok":1}')
  })
  it('marks a failed tool result as error', () => {
    const m = [...history]
    m[2] = msg(3, 1, 'user', [{ type: 'tool_result', tool_use_id: 'c1', content: 'boom', is_error: true }])
    expect((buildItems(m)[2] as any).status).toBe('error')
  })
  it('hides the active run but keeps its user text (it is rebuilt from events)', () => {
    expect(buildItems(history, 1).map(i => i.kind)).toEqual(['user'])
  })
})

describe('applyEvent', () => {
  it('appends text, starts a new text item after a tool card, tracks steps and end', () => {
    const items: Item[] = []
    applyEvent(items, { type: 'text', data: { text: 'he' } })
    applyEvent(items, { type: 'text', data: { text: 'llo' } })
    applyEvent(items, { type: 'tool_start', data: { workflow: 'wf', input: { a: 1 } } })
    applyEvent(items, { type: 'tool_step', data: { workflow: 'wf', task: 'sap.read_table', seq: 1, kind: 'task', status: 'running' } })
    applyEvent(items, { type: 'tool_step', data: { workflow: 'wf', task: 'sap.read_table', seq: 1, kind: 'task', status: 'ok' } })
    applyEvent(items, { type: 'waiting', data: { workflow: 'wf', resume_at: '2026-01-01T00:00:10+00:00' } })
    expect((items[1] as any).status).toBe('waiting')
    applyEvent(items, { type: 'tool_end', data: { workflow: 'wf', status: 'ok' } })
    applyEvent(items, { type: 'text', data: { text: 'next' } })
    expect(items.map(i => i.kind)).toEqual(['assistant', 'tool', 'assistant'])
    expect((items[0] as any).text).toBe('hello')
    const tool = items[1] as any
    expect(tool.status).toBe('ok')
    expect(tool.steps).toEqual([{ seq: 1, task: 'sap.read_table', status: 'ok' }])
  })
})
```

- [ ] **Step 2: Run to verify it fails** — `pnpm exec vitest run src/messages.test.ts` — FAIL (cannot resolve `./messages`).

- [ ] **Step 3: Implement** — `src/messages.ts`:
```ts
export interface Msg { id: number; run_id: number | null; role: 'user' | 'assistant'; content: string }
export type ToolItem = {
  kind: 'tool'; id: string; name: string; input: any; output?: string; isError?: boolean
  status: 'running' | 'waiting' | 'ok' | 'error'; steps: { seq: number; task: string; status: string }[]
}
export type Item = { kind: 'user' | 'assistant'; text: string } | ToolItem

export function buildItems(messages: Msg[], hideRunId: number | null = null): Item[] {
  const items: Item[] = [], tools = new Map<string, ToolItem>()
  for (const m of messages) {
    const hide = hideRunId !== null && m.run_id === hideRunId && m.role === 'assistant'
    const hideResult = hideRunId !== null && m.run_id === hideRunId
    for (const b of JSON.parse(m.content) as any[]) {
      if (b.type === 'text' && m.role === 'user') items.push({ kind: 'user', text: b.text })
      else if (b.type === 'text' && !hide) items.push({ kind: 'assistant', text: b.text })
      else if (b.type === 'tool_use' && !hide) {
        const t: ToolItem = { kind: 'tool', id: b.id, name: b.name, input: b.input, status: 'running', steps: [] }
        tools.set(b.id, t); items.push(t)
      } else if (b.type === 'tool_result' && !hideResult) {
        const t = tools.get(b.tool_use_id)
        if (t) { t.output = b.content; t.isError = b.is_error; t.status = b.is_error ? 'error' : 'ok' }
      }
    }
  }
  return items
}

/** Apply one live run event to the item list (mutates; the list is a Vue ref). */
export function applyEvent(items: Item[], ev: { type: string; data: any }): void {
  const lastTool = () => [...items].reverse().find((i): i is ToolItem => i.kind === 'tool' && i.status !== 'ok' && i.status !== 'error')
  const d = ev.data
  if (ev.type === 'text') {
    const last = items[items.length - 1]
    if (last && last.kind === 'assistant') last.text += d.text
    else items.push({ kind: 'assistant', text: d.text })
  } else if (ev.type === 'tool_start') {
    items.push({ kind: 'tool', id: `live-${items.length}`, name: d.workflow, input: d.input, status: 'running', steps: [] })
  } else if (ev.type === 'tool_step') {
    const t = lastTool()
    if (!t) return
    const s = t.steps.find(x => x.seq === d.seq)
    if (s) s.status = d.status
    else t.steps.push({ seq: d.seq, task: d.task, status: d.status })
  } else if (ev.type === 'waiting') {
    const t = lastTool(); if (t) t.status = 'waiting'
  } else if (ev.type === 'tool_end') {
    const t = lastTool(); if (t) { t.status = d.status === 'ok' ? 'ok' : 'error' }
  }
}
```

- [ ] **Step 4: Run to verify it passes** — `pnpm exec vitest run src/messages.test.ts` — Expected: `4 passed`.

- [ ] **Step 5: Chat page** — `src/pages/Chat.vue`:
```vue
<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { del, get, patch, post } from '../api'
import { applyEvent, buildItems, type Item, type Msg } from '../messages'
import ConfirmModal from '../components/ConfirmModal.vue'
import StatusPill from '../components/StatusPill.vue'
import { toast } from '../toast'
import Icon from '../components/Icon.vue'
import { layout, toggleThreads, setThreadsCollapsed } from '../layout'

const thopen = ref(false), small = window.matchMedia('(max-width: 1000px)')
const listEl = ref<HTMLElement | null>(null), openBtn = ref<HTMLElement | null>(null)
const chats = ref<any[]>([]), current = ref<any | null>(null), items = ref<Item[]>([])
const providers = ref<Record<string, string[]>>({}), provider = ref(''), model = ref('')
const text = ref(''), activeRun = ref<number | null>(null), resumeAt = ref<string | null>(null)
const confirmDel = ref<any | null>(null)
let es: EventSource | null = null, lastEvent = 0, retry: number | undefined, messages: Msg[] = []

async function loadChats() { chats.value = await get('api/chats') }
async function loadMessages() {
  if (!current.value) return
  messages = await get(`api/chats/${current.value.id}/messages`)
  items.value = buildItems(messages, activeRun.value)
}
function closeStream() { es?.close(); es = null; clearTimeout(retry) }

function attach(runId: number, after = 0) {
  closeStream()
  activeRun.value = runId; lastEvent = after
  items.value = buildItems(messages, runId)
  if (after === 0) items.value = buildItems(messages, runId)
  es = new EventSource(`api/runs/${runId}/events?after=${lastEvent}`)
  es.onmessage = async (e) => {
    lastEvent = Number(e.lastEventId) || lastEvent
    const ev = JSON.parse(e.data)
    if (ev.type === 'waiting') resumeAt.value = ev.data.resume_at
    if (ev.type === 'tool_end') resumeAt.value = null
    if (['done', 'error', 'cancelled'].includes(ev.type)) {
      closeStream(); activeRun.value = null; resumeAt.value = null
      if (ev.type === 'error') toast(ev.data.error || 'The run failed.')
      await loadMessages(); await loadChats(); return
    }
    applyEvent(items.value, ev)
  }
  // EventSource reconnects with Last-Event-ID, not our ?after=, so reopen by hand.
  es.onerror = () => { if (activeRun.value === runId) { es?.close(); retry = window.setTimeout(() => attach(runId, lastEvent), 1000) } }
}

async function select(c: any) {
  closeStream(); activeRun.value = null; current.value = c
  await loadMessages()
  if (['running', 'waiting'].includes(c.last_run_status)) attach(c.last_run_id)
}
async function newChat() {
  if (!provider.value || !model.value) return toast('Choose a provider and model first.')
  try {
    const { id } = await post('api/chats', { provider: provider.value, model: model.value })
    await loadChats(); await select(chats.value.find(c => c.id === id))
  } catch (e) { toast(e) }
}
async function changeModel() {
  if (!current.value) return
  try { await patch(`api/chats/${current.value.id}`, { provider: current.value.provider, model: current.value.model }) } catch (e) { toast(e) }
}
async function send() {
  if (!current.value || !text.value.trim() || activeRun.value) return
  const t = text.value; text.value = ''
  try {
    const { run_id } = await post(`api/chats/${current.value.id}/runs`, { text: t })
    messages = await get(`api/chats/${current.value.id}/messages`)
    attach(run_id)
  } catch (e) { text.value = t; toast(e) }
}
async function cancel() { if (activeRun.value) await post(`api/runs/${activeRun.value}/cancel`).catch(toast) }
async function remove() {
  const c = confirmDel.value; confirmDel.value = null
  await del(`api/chats/${c.id}`).catch(toast)
  if (current.value?.id === c.id) { current.value = null; items.value = []; closeStream(); activeRun.value = null }
  await loadChats()
}

onMounted(async () => {
  providers.value = await get('api/providers')
  provider.value = Object.keys(providers.value)[0] ?? ''
  model.value = providers.value[provider.value]?.[0] ?? ''
  await loadChats()
  if (chats.value[0]) await select(chats.value[0])
})
watch(thopen, async (o) => {
  if (o) { await nextTick(); (listEl.value?.querySelector<HTMLElement>('.thread[aria-current="true"]') ?? listEl.value?.querySelector<HTMLElement>('.thclose'))?.focus() }
  else if (small.matches) openBtn.value?.focus()
})
const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape' && thopen.value) thopen.value = false }
const onSmall = () => { if (!small.matches) thopen.value = false }
onMounted(() => { window.addEventListener('keydown', onEsc); small.addEventListener('change', onSmall) })
onBeforeUnmount(() => { closeStream(); window.removeEventListener('keydown', onEsc); small.removeEventListener('change', onSmall) })
</script>

<template>
  <section class="chat" :class="{ thc: layout.threadsCollapsed, thopen }">
    <div class="thscrim" @click="thopen = false" />
    <aside id="threads" ref="listEl" class="threads" :role="thopen ? 'dialog' : undefined" :aria-modal="thopen ? 'true' : undefined" aria-label="Chats">
      <div class="thbar">
        <span class="ttl">Chats</span>
        <button class="iconbtn thclose" aria-label="Close chat list" title="Close chat list" @click="thopen = false"><Icon name="close" /></button>
        <button class="iconbtn thtg" :aria-expanded="!layout.threadsCollapsed" aria-controls="threads"
                :title="layout.threadsCollapsed ? 'Expand chat list (Ctrl+Shift+B)' : 'Collapse chat list (Ctrl+Shift+B)'"
                :aria-label="layout.threadsCollapsed ? 'Expand chat list' : 'Collapse chat list'" @click="toggleThreads">
          <Icon :name="layout.threadsCollapsed ? 'expand' : 'collapse'" /></button>
      </div>
      <div class="rail">
        <button class="iconbtn" title="New chat" aria-label="New chat" @click="setThreadsCollapsed(false)"><Icon name="plus" /></button>
        <button v-for="c in chats" :key="c.id" class="rt" :title="c.title" :aria-label="c.title"
                :aria-current="current?.id === c.id ? 'true' : undefined" @click="select(c)"><span class="dot" :class="c.last_run_status" /></button>
      </div>
      <div class="top">
        <div class="row">
          <select class="field" v-model="provider" aria-label="Provider" @change="model = providers[provider]?.[0] ?? ''"><option v-for="(_, p) in providers" :key="p">{{ p }}</option></select>
          <select class="field" v-model="model" aria-label="Model"><option v-for="m in providers[provider] ?? []" :key="m">{{ m }}</option></select>
        </div>
        <button class="btn primary" @click="newChat"><Icon name="plus" />New chat</button>
      </div>
      <div class="tlist">
        <div v-for="c in chats" :key="c.id" class="row">
          <button class="thread" style="flex:1" :aria-current="current?.id === c.id ? 'true' : undefined" @click="select(c); thopen = false"><b>{{ c.title }}</b><span class="dot" :class="c.last_run_status" /></button>
          <button class="iconbtn" :aria-label="`Delete chat ${c.title}`" title="Delete chat" @click="confirmDel = c"><Icon name="trash" /></button>
        </div>
        <p v-if="!chats.length" class="muted">No chats yet.</p>
      </div>
    </aside>

    <div class="conv">
      <div v-if="!Object.keys(providers).length" class="callout"><b>No provider is configured.</b><span>An admin must set an API key under Settings.</span></div>
      <button ref="openBtn" class="btn sm chatsbtn" aria-controls="threads" :aria-expanded="thopen" @click="thopen = true">Chats</button>
      <div class="chat-main" v-if="current">
        <div class="row">
          <select class="field" style="width:auto" v-model="current.provider" @change="current.model = providers[current.provider]?.[0] ?? current.model; changeModel()">
            <option v-for="(_, p) in providers" :key="p">{{ p }}</option></select>
          <select class="field" style="width:auto" v-model="current.model" @change="changeModel"><option v-for="m in providers[current.provider] ?? []" :key="m">{{ m }}</option></select>
          <StatusPill v-if="activeRun" :status="resumeAt ? 'waiting' : 'running'" />
          <span v-if="resumeAt" class="muted mono">next check {{ resumeAt }}</span>
          <button v-if="activeRun" class="btn sm danger" @click="cancel">Cancel run</button>
        </div>
        <div class="msgs">
          <template v-for="(it, i) in items" :key="i">
            <div v-if="it.kind === 'user'" class="bubble user">{{ it.text }}</div>
            <div v-else-if="it.kind === 'assistant'" class="bubble assistant">{{ it.text }}</div>
            <details v-else class="toolcard" :open="it.status === 'running' || it.status === 'waiting'">
              <summary><b class="mono">{{ it.name }}</b> <StatusPill :status="it.status" /></summary>
              <pre>{{ JSON.stringify(it.input, null, 2) }}</pre>
              <div v-for="s in it.steps" :key="s.seq" class="muted mono" style="margin-top:4px">{{ s.seq }} · {{ s.task }} · {{ s.status }}</div>
              <pre v-if="it.output">{{ it.output }}</pre>
            </details>
          </template>
        </div>
        <form class="row" @submit.prevent="send">
          <input class="field" style="flex:1" v-model="text" :disabled="!!activeRun" placeholder="Message DXC Sage" aria-label="Message">
          <button class="btn primary" :disabled="!!activeRun || !text.trim()">Send</button>
        </form>
      </div>
      <div v-else class="muted">Choose a chat or start a new one.</div>
    </div>
    <ConfirmModal :open="!!confirmDel" title="Delete this chat?" confirm-label="Delete chat"
      text="The chat disappears from your list. Its run records and the audit log are kept." @confirm="remove" @cancel="confirmDel = null" />
  </section>
</template>
```

`src/pages/MyUsage.vue`:
```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { get } from '../api'
import DataTable from '../components/DataTable.vue'

const rows = ref<any[]>([])
onMounted(async () => (rows.value = (await get<any[]>('api/usage/me')).map(r => ({ ...r, id: r.day }))))
const columns = [
  { key: 'day', label: 'Day', mono: true }, { key: 'requests', label: 'Requests', mono: true },
  { key: 'tokens_in', label: 'Tokens in', mono: true }, { key: 'tokens_out', label: 'Tokens out', mono: true },
  { key: 'workflow_calls', label: 'Workflow calls', mono: true }, { key: 'task_calls', label: 'Task calls', mono: true },
]
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>My usage</h1><p>Counts only. There are no limits.</p></div></div>
    <DataTable :columns="columns" :rows="rows" />
  </section>
</template>
```

- [ ] **Step 6: Re-run the unit test** — `pnpm exec vitest run src/messages.test.ts` — Expected: `4 passed`.

---

### Task 3: Admin pages

**Files:**
- Create: `src/pages/admin/{Users.vue,Systems.vue,Workflows.vue,WorkflowSetup.vue,Health.vue,Settings.vue,Runs.vue,Audit.vue,Usage.vue}`

**Interfaces:**
- Consumes (all admin): `GET/POST api/users`, `PATCH api/users/{id}`, `POST api/users/{id}/reset-password`; `GET/POST api/systems`, `PATCH api/systems/{id}`, `PUT api/systems/{id}/credentials`, `POST api/systems/{id}/status|test`; `GET api/workflows`, `PUT api/workflows/{n}/state`, `PUT .../systems/{id}`, `POST .../enable|disable|check`, `GET .../guide`; `GET api/health/matrix`, `POST api/health/recheck`; `GET/PUT api/settings`; `GET api/runs`, `GET api/runs/{id}/detail`; `GET api/audit`, `GET api/audit/export.csv`, `POST api/audit/verify`; `GET api/usage`.

- [ ] **Step 1: Users** — `src/pages/admin/Users.vue`:
```vue
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
```

- [ ] **Step 2: Systems** — `src/pages/admin/Systems.vue`:
```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { get, patch, post, put } from '../../api'
import DataTable from '../../components/DataTable.vue'
import Drawer from '../../components/Drawer.vue'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

const systems = ref<any[]>([]), sel = ref<any | null>(null), creating = ref(false)
const blank = () => ({ label: '', sid: '', description: '', ashost: '', sysnr: '00', client: '100', rfc_user: '', rfc_password: '' })
const form = ref(blank()), cred = ref({ user: '', password: '' }), testMsg = ref('')
const load = async () => (systems.value = await get('api/systems'))
async function create() {
  try {
    const r = await post('api/systems', form.value)
    toast(r.test.ok ? `${r.label} registered and active.` : `${r.label} saved as inactive: ${r.test.message || r.test.stage}`)
    creating.value = false; form.value = blank(); await load()
  } catch (e) { toast(e) }
}
function open(s: any) { sel.value = { ...s }; cred.value = { user: s.rfc_user, password: '' }; testMsg.value = '' }
async function save() {
  const { label, sid, description, ashost, sysnr, client } = sel.value
  try { await patch(`api/systems/${sel.value.id}`, { label, sid, description, ashost, sysnr, client }); toast('Saved'); await load() } catch (e) { toast(e) }
}
async function rotate() {
  try { await put(`api/systems/${sel.value.id}/credentials`, cred.value); cred.value.password = ''; toast('Credentials updated. Run a test.') } catch (e) { toast(e) }
}
async function test() { const r = await post(`api/systems/${sel.value.id}/test`); testMsg.value = r.ok ? 'Connected and logged in.' : `${r.stage}: ${r.message}` }
async function setStatus(status: string) {
  try { await post(`api/systems/${sel.value.id}/status`, { status }); sel.value.status = status; await load() } catch (e) { toast(e) }
}
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>Systems</h1><p>SAP systems Sage can reach through one RFC account each. Systems are disabled, never deleted.</p></div><span class="spacer" />
      <button class="btn primary" @click="creating = true">Register system</button></div>
    <DataTable clickable :rows="systems" @select="open" :columns="[{key:'label',label:'Label',mono:true},{key:'sid',label:'SID',mono:true},{key:'ashost',label:'Host',mono:true},{key:'client',label:'Client',mono:true},{key:'rfc_user',label:'RFC user',mono:true},{key:'status',label:'Status'}]">
      <template #status="{ row }"><StatusPill :status="row.status" /></template>
    </DataTable>

    <Drawer :open="creating" title="Register system" @close="creating = false">
      <label class="lbl">Label (for example TS3)<input class="field" v-model="form.label"></label>
      <label class="lbl">SID<input class="field" v-model="form.sid" maxlength="3"></label>
      <label class="lbl">Description<input class="field" v-model="form.description"></label>
      <label class="lbl">Application server host<input class="field" v-model="form.ashost"></label>
      <div class="row"><label class="lbl">System number<input class="field" v-model="form.sysnr" maxlength="2"></label>
        <label class="lbl">Client<input class="field" v-model="form.client" maxlength="3"></label></div>
      <div class="callout info"><span>The RFC account Sage logs in with. The password is stored encrypted and is never shown again.</span></div>
      <label class="lbl">RFC user<input class="field" v-model="form.rfc_user" autocomplete="off"></label>
      <label class="lbl">RFC password<input class="field" type="password" v-model="form.rfc_password" autocomplete="new-password"></label>
      <button class="btn primary" @click="create">Register and test connection</button>
    </Drawer>

    <Drawer :open="!!sel" :title="sel?.label ?? ''" @close="sel = null">
      <template v-if="sel">
        <div class="row"><StatusPill :status="sel.status" /><button class="btn sm" @click="test">Test connection</button>
          <button v-if="sel.status !== 'active'" class="btn sm" @click="setStatus('active')">Activate</button>
          <button v-if="sel.status !== 'disabled'" class="btn sm danger" @click="setStatus('disabled')">Disable</button></div>
        <div v-if="testMsg" class="callout info"><span>{{ testMsg }}</span></div>
        <label class="lbl">Label<input class="field" v-model="sel.label"></label>
        <label class="lbl">SID<input class="field" v-model="sel.sid" maxlength="3"></label>
        <label class="lbl">Description<input class="field" v-model="sel.description"></label>
        <label class="lbl">Host<input class="field" v-model="sel.ashost"></label>
        <div class="row"><label class="lbl">System number<input class="field" v-model="sel.sysnr"></label><label class="lbl">Client<input class="field" v-model="sel.client"></label></div>
        <button class="btn" @click="save">Save details</button>
        <h3 style="margin:8px 0 0;font-size:14px">RFC account</h3>
        <label class="lbl">RFC user<input class="field" v-model="cred.user" autocomplete="off"></label>
        <label class="lbl">New RFC password<input class="field" type="password" v-model="cred.password" autocomplete="new-password"></label>
        <button class="btn" :disabled="!cred.user || !cred.password" @click="rotate">Update credentials</button>
      </template>
    </Drawer>
  </section>
</template>
```

- [ ] **Step 3: Workflows list and setup guide** — `src/pages/admin/Workflows.vue`:
```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { get, put } from '../../api'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

const router = useRouter()
const workflows = ref<any[]>([]), systems = ref<any[]>([]), pick = ref<Record<string, number>>({})
async function load() { workflows.value = await get('api/workflows'); systems.value = (await get<any[]>('api/systems')).filter(s => s.status === 'active') }
async function setState(w: any) { try { await put(`api/workflows/${w.name}/state`, { enabled: !w.enabled }); await load() } catch (e) { toast(e) } }
async function setUp(w: any) {
  const id = pick.value[w.name]
  if (!id) return toast('Choose a system first.')
  try { await put(`api/workflows/${w.name}/systems/${id}`, { settings: {} }); router.push(`/admin/workflows/${w.name}/${id}`) } catch (e) { toast(e) }
}
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>Workflows</h1><p>The model sees a workflow only after you set it up and enable it on a system.</p></div></div>
    <div v-for="w in workflows" :key="w.name" class="card" style="margin-bottom:14px">
      <div class="card-h"><h2 class="mono">{{ w.name }}</h2><StatusPill :status="w.enabled ? 'enabled' : 'disabled'" />
        <span v-if="w.durable" class="pill off">long-running</span><span class="spacer" />
        <button class="btn sm" @click="setState(w)">{{ w.enabled ? 'Disable workflow' : 'Enable workflow' }}</button></div>
      <div class="card-b" style="display:grid;gap:10px">
        <p class="muted" style="margin:0">{{ w.description }}</p>
        <table><thead><tr><th>System</th><th>Setup</th><th>Last health check</th><th></th></tr></thead><tbody>
          <tr v-for="b in w.bindings" :key="b.system_id"><td class="mono">{{ b.label }} ({{ b.sid }})</td><td><StatusPill :status="b.status" /></td>
            <td><StatusPill :status="b.health" /></td>
            <td><router-link class="btn sm" :to="`/admin/workflows/${w.name}/${b.system_id}`">Open setup guide</router-link></td></tr>
          <tr v-if="!w.bindings.length"><td colspan="4" class="muted">Not set up on any system.</td></tr></tbody></table>
        <div class="row"><select class="field" style="width:auto" v-model="pick[w.name]"><option :value="undefined" disabled>Choose a system</option>
          <option v-for="s in systems" :key="s.id" :value="s.id">{{ s.label }} ({{ s.sid }})</option></select>
          <button class="btn primary" @click="setUp(w)">Set up on this system</button></div>
      </div>
    </div>
  </section>
</template>
```

`src/pages/admin/WorkflowSetup.vue`:
```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { get, post, put } from '../../api'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

const { name, systemId } = useRoute().params as { name: string; systemId: string }
const base = `api/workflows/${name}/systems/${systemId}`
const guide = ref<any | null>(null), wf = ref<any | null>(null), binding = ref<any | null>(null), values = ref<Record<string, string>>({})
async function load() {
  guide.value = await get(`${base}/guide`)
  wf.value = (await get<any[]>('api/workflows')).find(w => w.name === name)
  binding.value = wf.value.bindings.find((b: any) => String(b.system_id) === systemId)
  values.value = { ...(binding.value?.settings ?? {}) }
}
async function saveSettings() { try { await put(base, { settings: values.value }); toast('Settings saved'); await load() } catch (e) { toast(e) } }
async function check() { try { await post(`${base}/check`); await load() } catch (e) { toast(e) } }
async function enable() { try { await post(`${base}/enable`); toast('Enabled'); await load() } catch (e) { toast(e) } }
async function disable() { await post(`${base}/disable`); await load() }
async function copyMarkdown() {
  try { await navigator.clipboard.writeText(await get(`${base}/guide?format=markdown`)); toast('Guide copied as Markdown') } catch (e) { toast(e) }
}
onMounted(() => load().catch(toast))
</script>
<template>
  <section class="page" v-if="guide">
    <div class="page-head"><div><h1><span class="mono">{{ guide.workflow }}</span> on {{ guide.system.label }}</h1>
      <p>{{ guide.description }}</p></div><span class="spacer" />
      <router-link class="btn" to="/admin/workflows">Back</router-link></div>
    <div class="card" style="margin-bottom:14px"><div class="card-b row">
      <StatusPill :status="binding?.status" /><span class="muted">health</span><StatusPill :status="binding?.health" />
      <span class="spacer" />
      <button class="btn" @click="check">Run health check</button>
      <button class="btn" @click="copyMarkdown">Copy guide as Markdown</button>
      <button v-if="binding?.status !== 'enabled'" class="btn primary" @click="enable">Enable</button>
      <button v-else class="btn danger" @click="disable">Disable</button>
    </div></div>

    <div v-if="wf?.settings.length" class="card" style="margin-bottom:14px"><div class="card-h"><h2>Settings for this system</h2></div>
      <div class="card-b" style="display:grid;gap:10px">
        <label v-for="s in wf.settings" :key="s.key" class="lbl">{{ s.label }}<input class="field" v-model="values[s.key]">
          <span class="muted">{{ s.description }}</span></label>
        <div><button class="btn" @click="saveSettings">Save settings</button></div>
      </div></div>

    <div class="card" style="margin-bottom:14px"><div class="card-h"><h2>Setup steps on {{ guide.system.sid }} (client {{ guide.system.client }})</h2>
      <span class="sub">RFC user <span class="mono">{{ guide.system.rfc_user }}</span></span></div>
      <div class="card-b" style="display:grid;gap:12px">
        <div v-for="(s, i) in guide.steps" :key="i" style="border-bottom:1px solid var(--line);padding-bottom:10px">
          <div class="row"><b>{{ i + 1 }}. {{ s.title }}</b><StatusPill :status="s.status" /></div>
          <p style="margin:4px 0">{{ s.text }}</p>
          <p v-if="s.message" class="muted mono" style="margin:0">Last check: {{ s.message }}</p>
          <details v-if="s.source_text"><summary>ABAP source ({{ s.source }})</summary><pre class="out">{{ s.source_text }}</pre></details>
        </div>
      </div></div>

    <div class="card"><div class="card-h"><h2>Authorizations for the RFC user's role</h2><span class="sub">Hand this table to Basis</span></div>
      <div class="card-b"><table><thead><tr><th>Object</th><th>Field</th><th>Value</th></tr></thead><tbody>
        <tr v-for="(r, i) in guide.auth_table" :key="i"><td class="mono">{{ r[0] }}</td><td class="mono">{{ r[1] }}</td><td class="mono">{{ r[2] }}</td></tr></tbody></table></div></div>
  </section>
</template>
```

- [ ] **Step 4: Health matrix** — `src/pages/admin/Health.vue`:
```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { get, post } from '../../api'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

const m = ref<any>({ systems: [], workflows: [], cells: [] })
const load = async () => (m.value = await get('api/health/matrix'))
const cell = (w: string, s: number) => m.value.cells.find((c: any) => c.workflow === w && c.system_id === s)
async function recheck(system_id?: number) { try { await post('api/health/recheck', { system_id: system_id ?? null }); await load(); toast('Re-checked') } catch (e) { toast(e) } }
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>Health</h1><p>Per system and workflow. Checks are read-only and never run a write function.</p></div><span class="spacer" />
      <button class="btn primary" @click="recheck()">Re-check all</button></div>
    <div class="card"><div class="tablewrap"><table class="matrix">
      <thead><tr><th style="text-align:left">System</th><th v-for="w in m.workflows" :key="w" class="mono">{{ w }}</th><th></th></tr></thead>
      <tbody>
        <tr v-for="s in m.systems" :key="s.id"><td style="text-align:left" class="mono">{{ s.label }} <StatusPill :status="s.status" /></td>
          <td v-for="w in m.workflows" :key="w">
            <router-link v-if="cell(w, s.id)" :to="`/admin/workflows/${w}/${s.id}`"><StatusPill :status="cell(w, s.id).health" /></router-link>
            <span v-else class="muted">not set up</span></td>
          <td><button class="btn sm" @click="recheck(s.id)">Re-check</button></td></tr>
        <tr v-if="!m.systems.length"><td :colspan="m.workflows.length + 2" class="muted">No systems registered yet.</td></tr>
      </tbody></table></div></div>
  </section>
</template>
```

- [ ] **Step 5: Settings, Runs, Audit, Usage**

`src/pages/admin/Settings.vue`:
```vue
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { get, put } from '../../api'
import DataTable from '../../components/DataTable.vue'
import Drawer from '../../components/Drawer.vue'
import StatusPill from '../../components/StatusPill.vue'
import { toast } from '../../toast'

const raw = ref<Record<string, any>>({}), sel = ref<string | null>(null), text = ref('')
const isSecret = (v: any) => v && typeof v === 'object' && 'set' in v && Object.keys(v).length === 1
const rows = computed(() => Object.entries(raw.value).map(([key, v]) => ({ id: key, key, value: isSecret(v) ? (v.set ? 'set' : 'not set') : JSON.stringify(v), secret: isSecret(v) })))
const load = async () => (raw.value = await get('api/settings'))
function open(r: any) { sel.value = r.key; text.value = r.secret ? '' : JSON.stringify(raw.value[r.key], null, 2) }
async function save() {
  const secret = isSecret(raw.value[sel.value!])
  try {
    await put('api/settings', { key: sel.value, value: secret ? text.value : JSON.parse(text.value) })
    toast('Saved'); sel.value = null; await load()
  } catch (e) { toast(e instanceof SyntaxError ? 'The value is not valid JSON.' : e) }
}
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>Settings</h1><p>All configuration lives here. Secret values are write-only.</p></div></div>
    <DataTable clickable :rows="rows" @select="open" :columns="[{key:'key',label:'Setting',mono:true},{key:'value',label:'Value',mono:true}]">
      <template #value="{ row }"><StatusPill v-if="row.secret" :status="row.value === 'set' ? 'ok' : 'warn'" /><span v-else class="mono" style="word-break:break-all">{{ row.value.length > 90 ? row.value.slice(0, 90) + '…' : row.value }}</span></template>
    </DataTable>
    <Drawer :open="!!sel" :title="sel ?? ''" @close="sel = null">
      <label class="lbl">{{ isSecret(raw[sel ?? '']) ? 'New secret value (never shown again)' : 'Value (JSON)' }}
        <textarea v-if="!isSecret(raw[sel ?? ''])" class="field mono" rows="14" v-model="text" />
        <input v-else class="field" type="password" v-model="text" autocomplete="new-password"></label>
      <button class="btn primary" @click="save">Save</button>
    </Drawer>
  </section>
</template>
```

`src/pages/admin/Runs.vue`:
```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { get } from '../../api'
import DataTable from '../../components/DataTable.vue'
import Drawer from '../../components/Drawer.vue'
import StatusPill from '../../components/StatusPill.vue'

const runs = ref<any[]>([]), status = ref(''), detail = ref<any | null>(null)
const load = async () => (runs.value = await get(`api/runs${status.value ? `?status=${status.value}` : ''}`))
async function open(r: any) { detail.value = await get(`api/runs/${r.id}/detail`) }
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>Runs</h1><p>Every request, including runs of deleted chats.</p></div><span class="spacer" />
      <select class="field" style="width:auto" v-model="status" @change="load"><option value="">All statuses</option>
        <option v-for="s in ['running','waiting','done','failed','cancelled']" :key="s">{{ s }}</option></select></div>
    <DataTable clickable :rows="runs" @select="open" :columns="[{key:'id',label:'Run',mono:true},{key:'username',label:'User'},{key:'title',label:'Chat'},{key:'model',label:'Model',mono:true},{key:'status',label:'Status'},{key:'tokens_in',label:'Tokens in',mono:true},{key:'tokens_out',label:'Tokens out',mono:true},{key:'started_at',label:'Started',mono:true}]">
      <template #status="{ row }"><StatusPill :status="row.status" /><span v-if="row.chat_deleted" class="muted"> · chat deleted</span></template>
    </DataTable>
    <Drawer :open="!!detail" :title="`Run ${detail?.run.id ?? ''}`" @close="detail = null">
      <template v-if="detail">
        <div v-if="detail.run.error" class="callout"><b>{{ detail.run.error }}</b></div>
        <div v-for="c in detail.tool_calls" :key="c.id" class="toolcard">
          <b class="mono">{{ c.workflow }}</b> <StatusPill :status="c.status" />
          <pre>{{ c.input }}</pre>
          <div v-for="s in c.steps" :key="s.id" class="muted mono" style="margin-top:6px">{{ s.seq }} · {{ s.kind }} · {{ s.name }} · {{ s.status }}<span v-if="s.error"> · {{ s.error }}</span></div>
          <pre v-if="c.output">{{ c.output }}</pre>
        </div>
        <div v-if="!detail.tool_calls.length" class="muted">No workflow calls in this run.</div>
      </template>
    </Drawer>
  </section>
</template>
```

`src/pages/admin/Audit.vue`:
```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { get, post } from '../../api'
import DataTable from '../../components/DataTable.vue'
import { toast } from '../../toast'

const rows = ref<any[]>([]), event = ref(''), actor = ref('')
async function load() {
  const q = new URLSearchParams(); if (event.value) q.set('event', event.value); if (actor.value) q.set('actor', actor.value)
  rows.value = await get(`api/audit?${q}`)
}
async function verify() {
  const r = await post('api/audit/verify')
  toast(r.ok ? 'Audit chain verified. No tampering found.' : `Chain broken at entry ${r.bad_id}.`)
}
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>Audit log</h1><p>Append-only and hash-chained.</p></div><span class="spacer" />
      <button class="btn" @click="verify">Verify chain</button><a class="btn" href="api/audit/export.csv" download>Export CSV</a></div>
    <div class="row" style="margin-bottom:12px"><input class="field" style="width:220px" v-model="event" placeholder="Event, e.g. tool.step" @keyup.enter="load">
      <input class="field" style="width:200px" v-model="actor" placeholder="Actor" @keyup.enter="load"><button class="btn" @click="load">Filter</button></div>
    <DataTable :rows="rows" :columns="[{key:'id',label:'#',mono:true},{key:'ts',label:'Time',mono:true},{key:'event',label:'Event',mono:true},{key:'actor',label:'Actor'},{key:'run_id',label:'Run',mono:true},{key:'detail',label:'Detail',mono:true}]">
      <template #detail="{ row }"><span style="word-break:break-all">{{ row.detail.length > 140 ? row.detail.slice(0, 140) + '…' : row.detail }}</span></template>
    </DataTable>
  </section>
</template>
```

`src/pages/admin/Usage.vue`:
```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { get } from '../../api'
import DataTable from '../../components/DataTable.vue'

const rows = ref<any[]>([])
onMounted(async () => (rows.value = (await get<any[]>('api/usage')).map(r => ({ ...r, id: `${r.user_id}-${r.day}` }))))
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>Usage (all users)</h1><p>Counts per user and day. There are no limits.</p></div></div>
    <DataTable :rows="rows" :columns="[{key:'username',label:'User'},{key:'day',label:'Day',mono:true},{key:'requests',label:'Requests',mono:true},{key:'tokens_in',label:'Tokens in',mono:true},{key:'tokens_out',label:'Tokens out',mono:true},{key:'workflow_calls',label:'Workflow calls',mono:true},{key:'task_calls',label:'Task calls',mono:true}]" />
  </section>
</template>
```

- [ ] **Step 6: Type check and build, once**

Run: `cd sage_web; pnpm build`
Expected: `vue-tsc` passes and `vite build` writes `dist/`. Fix only errors in files from this plan. If `.nav.router-link-active` is not styled by `base.css`, add the rule from Task 1 Step 4 to `app.css`.

---

### Task 4: Container files, README, optional browser check, commit

**Files:**
- Create: `sage_web/Dockerfile`, `sage_web/nginx.conf`, `Applications/DXCSage/README.md`
- Modify: `Applications/DXCSage/docker-compose.yml`

- [ ] **Step 1: Write container files** (not built in this plan)

`sage_web/nginx.conf`:
```nginx
server {
  listen 80;
  root /usr/share/nginx/html;
  index index.html;
  location = /health { default_type application/json; return 200 '{"status":"ok"}'; }
  location /api/ {
    proxy_pass http://sage_api:29700;
    proxy_http_version 1.1;
    proxy_buffering off;            # keeps run events streaming
    proxy_read_timeout 3600s;
  }
  location / { try_files $uri /index.html; }
}
```

`sage_web/Dockerfile`:
```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

`docker-compose.yml`: add under `services:`
```yaml
  sage_web:
    build: ./sage_web
    ports: ["${SERVICE_BIND:-0.0.0.0}:29701:80"]
    extra_hosts: ["host.docker.internal:host-gateway"]
    depends_on: [sage_api]
    restart: unless-stopped
```

`README.md`:
```markdown
# DXC Sage

Small agentic harness (Claude and GPT) with SAP workflow tools. Two services: `sage_api` (port 29700) and `sage_web` (port 29701). Design: `docs/superpowers/specs/2026-11-24-dxc-sage-design.md`.

## Run with Docker
Put the SAP NW RFC SDK and a `pyrfc` wheel in `sage_api/vendor/` (licensed, not in git), then:

    docker compose up -d --build

Open `http://localhost:29701`. Copy `.env.example` to `.env` and set the bootstrap admin before the first start; the first sign-in forces a password change. Everything else (API keys, SAP systems, settings) is set in the app, as an admin.

## Run without Docker (development)

    cd sage_api; uv run uvicorn sage.app:create_app --factory --port 29700
    cd sage_web; pnpm install; pnpm dev

## First steps
1. Sign in as the bootstrap admin and change the password.
2. Settings: set the Claude and/or GPT API key.
3. Systems: register a SAP system and its RFC account.
4. Workflows: open `sap_readiness_check`, set it up on the system, follow the guide, run the health check, enable it.
5. Chat: ask for a readiness check on that system.

## Backups
Back up both volumes: `sage_data` (SQLite) and `sage_keys` (the master key). The key alone is useless and the DB without the key cannot decrypt stored passwords.

## Not verified yet
pyrfc against a real SAP system, the Claude and GPT network calls, and the custom `ZFM_*` function modules (specs are in the setup guide).
```

- [ ] **Step 2 (optional, ask first): smoke check in the browser pane**

Only if the user agrees: start `uv run uvicorn sage.app:create_app --factory --port 29700` (with `SAGE_BOOTSTRAP_ADMIN_USER` and `SAGE_BOOTSTRAP_ADMIN_PASSWORD` set in that shell) and `pnpm dev`, open `http://localhost:29701`, sign in, change the password, open Settings, Systems, Workflows. Report what loads. Nothing else is run.

- [ ] **Step 3: Commit once**

```powershell
cd D:\User\Documents\Programming\Applications\DXCSage
git add README.md docker-compose.yml sage_web docs
git commit -m "feat: DXC Sage frontend (chat, admin pages, setup guide, health matrix)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Self-Review (spec coverage)

- Login, forced password change, admin and user roles: Task 1.
- Chat with streaming, workflow cards with steps, provider/model picker per chat, cancel, delete with confirm, reload shows running or waiting run: Task 2.
- My usage and all-users usage (counts only): Tasks 2, 3.
- Admin: Users, Systems (register with RFC account, test, rotate credentials, disable), Workflows (set up per system, guide with live status, per-system settings, enable/disable), Health matrix with re-check, Settings (secrets write-only), Runs (including deleted chats, steps), Audit (filter, export, verify): Task 3.
- Relative URLs and hash routing for ServiceHub, `/health` on nginx: Tasks 1, 4. Drawers for admin, modal only for chat delete: Tasks 1, 3, 2.
- Shell: 56px top bar, collapsible main menu (Ctrl+B) and chat list (Ctrl+Shift+B), 60px icon-only sidebar and chat drawer at 1000px and below: Task 1 Step 3b, Task 2 Step 5.
- Not built: write-confirmation, SSO, email watchers, Docker build run, browser smoke (optional).
