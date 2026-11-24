import { reactive } from 'vue'
import { get } from './api'

export interface Me { id: number; username: string; role: string; must_change_password: boolean }
export const session = reactive<{ user: Me | null; loaded: boolean }>({ user: null, loaded: false })

export async function loadMe() {
  try { session.user = await get<Me>('api/auth/me') } catch { session.user = null }
  session.loaded = true
}
