import { expect, test } from '@playwright/test'

import { createConfirmedUser, deleteUser, type TestUser } from './supabaseAdmin'

// Plan A.5: sign up, log in, land on Chat, reload and stay signed in, log out and get
// redirected; `/` while signed out redirects to login; `/me` returns the signed-in email.

let user: TestUser

test.beforeAll(async () => {
  user = await createConfirmedUser()
})

test.afterAll(async () => {
  if (user) await deleteUser(user.id)
})

async function logIn(page: import('@playwright/test').Page, email: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Log in' }).click()
}

test('signed-out visit to / redirects to /login', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByText('Log in', { exact: true }).first()).toBeVisible()
})

test('signed-out visit to /ingestion redirects to /login', async ({ page }) => {
  await page.goto('/ingestion')
  await expect(page).toHaveURL(/\/login$/)
})

test('wrong password shows an error', async ({ page }) => {
  await logIn(page, user.email, 'definitely-wrong-password')
  await expect(page.getByRole('alert')).toContainText(/invalid/i)
  await expect(page).toHaveURL(/\/login$/)
})

test('log in, /me email, nav, reload persistence, log out', async ({ page }) => {
  const meResponse = page.waitForResponse((r) => r.url().endsWith('/me'))
  await logIn(page, user.email, user.password)

  // Lands on Chat (default route).
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByText('How can I help?')).toBeVisible()

  // Backend verified the Supabase JWT and returned our email.
  const me = await meResponse
  expect(me.status()).toBe(200)
  expect(await me.json()).toMatchObject({ id: user.id, email: user.email })
  await expect(page.getByTestId('me-email')).toHaveText(user.email)

  // Nav to Ingestion and back.
  await page.getByRole('link', { name: 'Ingestion' }).click()
  await expect(page).toHaveURL(/\/ingestion$/)
  await expect(page.getByRole('heading', { name: 'Ingestion' })).toBeVisible()
  await page.getByRole('link', { name: 'Chat' }).click()
  await expect(page).toHaveURL(/\/$/)

  // Reload keeps the session.
  await page.reload()
  await expect(page.getByText('How can I help?')).toBeVisible()
  await expect(page.getByTestId('me-email')).toHaveText(user.email)

  // Log out -> login page; protected route now redirects.
  await page.getByRole('button', { name: 'Log out' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
})

test('signed-in visit to /login redirects to Chat', async ({ page }) => {
  await logIn(page, user.email, user.password)
  await expect(page.getByText('How can I help?')).toBeVisible()
  await page.goto('/login')
  await expect(page).toHaveURL(/\/$/)
})

// The project requires email confirmation, so a real sign-up would send mail.
// Mock Supabase's /signup response to exercise the UI paths instead.
test('sign up with confirmation required shows the check-your-email notice', async ({ page }) => {
  await page.route('**/auth/v1/signup**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: crypto.randomUUID(),
        aud: 'authenticated',
        role: 'authenticated',
        email: 'new-user@example.com',
        confirmation_sent_at: new Date().toISOString(),
        app_metadata: { provider: 'email' },
        user_metadata: {},
        identities: [{ id: '1' }],
        created_at: new Date().toISOString(),
      }),
    }),
  )
  await page.goto('/login')
  await page.getByRole('button', { name: /sign up/i }).click()
  await expect(page.getByText('Create an account')).toBeVisible()
  await page.getByLabel('Email').fill('new-user@example.com')
  await page.getByLabel('Password').fill('a-good-password')
  await page.getByRole('button', { name: 'Sign up' }).click()
  await expect(page.getByRole('alert')).toContainText(/check your email/i)
  // Switched back to log-in mode.
  await expect(page.getByRole('button', { name: 'Log in' })).toBeVisible()
})

test('sign up error is shown', async ({ page }) => {
  await page.route('**/auth/v1/signup**', (route) =>
    route.fulfill({
      status: 422,
      contentType: 'application/json',
      body: JSON.stringify({ code: 422, error_code: 'user_already_exists', msg: 'User already registered' }),
    }),
  )
  await page.goto('/login')
  await page.getByRole('button', { name: /sign up/i }).click()
  await page.getByLabel('Email').fill('taken@example.com')
  await page.getByLabel('Password').fill('a-good-password')
  await page.getByRole('button', { name: 'Sign up' }).click()
  await expect(page.getByRole('alert')).toContainText(/already registered/i)
})
