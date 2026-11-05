import { readFileSync } from 'node:fs'
import path from 'node:path'
import { parseEnv } from 'node:util'

// Test-only helpers: use the backend's service-role key to create and delete
// throwaway confirmed users, so no confirmation email is ever sent.
const env = parseEnv(readFileSync(path.resolve(import.meta.dirname, '../../backend/.env'), 'utf8'))
const url = (env.SUPABASE_URL ?? '').replace(/\/$/, '')
const serviceKey = env.SUPABASE_SERVICE_ROLE_KEY ?? ''

const adminHeaders = {
  apikey: serviceKey,
  Authorization: `Bearer ${serviceKey}`,
  'Content-Type': 'application/json',
}

export type TestUser = { id: string; email: string; password: string }

export async function createConfirmedUser(): Promise<TestUser> {
  const email = `e2e-${crypto.randomUUID().slice(0, 8)}@example.com`
  const password = `E2e-${crypto.randomUUID()}`
  const res = await fetch(`${url}/auth/v1/admin/users`, {
    method: 'POST',
    headers: adminHeaders,
    body: JSON.stringify({ email, password, email_confirm: true }),
  })
  if (!res.ok) throw new Error(`createUser failed: ${res.status} ${await res.text()}`)
  const user = (await res.json()) as { id: string }
  return { id: user.id, email, password }
}

export async function deleteUser(id: string): Promise<void> {
  await fetch(`${url}/auth/v1/admin/users/${id}`, { method: 'DELETE', headers: adminHeaders })
}
