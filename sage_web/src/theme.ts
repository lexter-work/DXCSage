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
