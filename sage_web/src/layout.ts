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
