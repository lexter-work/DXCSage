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
