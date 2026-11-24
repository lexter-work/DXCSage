import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import { setUnauthorizedHandler } from './api'
import { session } from './session'
import { initTheme } from './theme'
import './styles/moss.css'
import './styles/app.css'

initTheme()
setUnauthorizedHandler(() => { session.user = null; router.push('/login') })
createApp(App).use(router).mount('#app')
