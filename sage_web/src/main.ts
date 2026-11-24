import { createApp } from 'vue'
import '@fontsource-variable/inter'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import App from './App.vue'
import { router } from './router'
import { setUnauthorizedHandler } from './api'
import { session } from './session'
import { initTheme } from './theme'
import { initShortcuts } from './layout'
import './styles/dxc.css'

initTheme()
initShortcuts()
setUnauthorizedHandler(() => { session.user = null; router.push('/login') })
createApp(App).use(router).mount('#app')
