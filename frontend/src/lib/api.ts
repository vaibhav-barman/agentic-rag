import { supabase } from '@/lib/supabase'

export const API_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Build request headers with the current Supabase access token attached. */
export async function authHeaders(extra?: HeadersInit): Promise<Headers> {
  const headers = new Headers(extra)
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return headers
}

/**
 * Raw fetch against the backend with the auth header attached.
 * Returns the Response untouched so callers can read streams (SSE).
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = await authHeaders(init.headers)
  const response = await fetch(`${API_URL}${path}`, { ...init, headers })
  if (!response.ok) {
    let message = response.statusText || `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') message = body.detail
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(response.status, message)
  }
  return response
}

/** JSON convenience wrapper around apiFetch. */
export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !headers.has('Content-Type') && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await apiFetch(path, { ...init, headers })
  return (await response.json()) as T
}

export type Me = { id: string; email: string | null }

export const getMe = () => apiJson<Me>('/me')
