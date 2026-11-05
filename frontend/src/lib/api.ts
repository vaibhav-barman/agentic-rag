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

// --- Threads & chat -------------------------------------------------------

export type Thread = { id: string; title: string | null; created_at: string; updated_at: string | null }

export type Source = {
  document_id: string
  filename: string
  chunk_index: number
  content: string
  similarity: number
}

export type Message = {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: Source[] | null
  created_at: string
}

export const listThreads = () => apiJson<Thread[]>('/threads')
export const createThread = () => apiJson<Thread>('/threads', { method: 'POST', body: '{}' })
export const deleteThread = (id: string) => apiFetch(`/threads/${id}`, { method: 'DELETE' })
export const listMessages = (threadId: string) => apiJson<Message[]>(`/threads/${threadId}/messages`)

export type ChatEvent =
  | { event: 'user_message'; data: { id: string } }
  | { event: 'delta'; data: { text: string } }
  | { event: 'sources'; data: { query: string; sources: Source[] } }
  | { event: 'done'; data: { message_id: string; title: string | null } }
  | { event: 'error'; data: { message: string } }

/** POST a chat message and yield SSE events as they arrive (fetch + stream reader). */
export async function* streamChat(
  threadId: string,
  content: string,
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const response = await apiFetch(`/threads/${threadId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ content }),
    signal,
  })
  if (!response.body) throw new Error('No response body')
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let boundary: number
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      let event = 'message'
      let data = ''
      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7)
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (data) yield { event, data: JSON.parse(data) } as ChatEvent
    }
  }
}

// --- Documents --------------------------------------------------------------

export type DocumentRow = {
  id: string
  filename: string
  status: 'processing' | 'completed' | 'failed'
  error: string | null
  chunk_count: number
  created_at: string
}

export const listDocuments = () => apiJson<DocumentRow[]>('/documents')
export const deleteDocument = (id: string) => apiFetch(`/documents/${id}`, { method: 'DELETE' })
export function uploadDocument(file: File) {
  const body = new FormData()
  body.append('file', file)
  return apiJson<DocumentRow>('/documents', { method: 'POST', body })
}
