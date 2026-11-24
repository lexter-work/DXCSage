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
