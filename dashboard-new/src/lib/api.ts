const API = location.origin

export async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 10000)
  try {
    const res = await fetch(`${API}${path}`, { credentials: 'same-origin', signal: controller.signal, ...init })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json()
  } finally {
    clearTimeout(timeout)
  }
}

export async function checkAuth(): Promise<boolean> {
  try {
    const d = await fetchJSON<{ authenticated: boolean }>('/auth/check')
    return d.authenticated
  } catch {
    return false
  }
}

export async function login(password: string): Promise<boolean> {
  const res = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
    credentials: 'same-origin',
  })
  return res.ok
}

export async function logout(): Promise<void> {
  await fetch(`${API}/auth/logout`, { method: 'POST', credentials: 'same-origin' })
}

export function getWSUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws/chat`
}
