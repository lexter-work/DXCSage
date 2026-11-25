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
    { path: '/admin/abap', component: () => import('./pages/admin/AbapObjects.vue'), meta: admin },
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
