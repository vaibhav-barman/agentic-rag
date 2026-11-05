import { expect, test, type Page } from '@playwright/test'

import { createConfirmedUser, deleteUser, type TestUser } from './supabaseAdmin'

// Live tests against the real backend, Supabase and Gemini model.
// Free models can be slow, so timeouts are generous.
test.describe.configure({ mode: 'serial', timeout: 180_000 })

let user: TestUser

test.beforeAll(async () => {
  user = await createConfirmedUser()
})

test.afterAll(async () => {
  if (user) await deleteUser(user.id)
})

async function logIn(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(user.email)
  await page.getByLabel('Password').fill(user.password)
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByText('How can I help?')).toBeVisible()
}

async function ask(page: Page, text: string) {
  const before = await page.getByTestId('message-assistant').count()
  await page.getByLabel('Message').fill(text)
  await page.getByLabel('Message').press('Enter')
  const answer = page.getByTestId('message-assistant').nth(before)
  await expect(answer).toBeVisible()
  // Wait for streaming to finish (the Send button comes back).
  await expect(page.getByRole('button', { name: 'Stop' })).toBeHidden({ timeout: 150_000 })
  await expect(answer.getByRole('alert')).toHaveCount(0)
  return answer
}

test('B.5: streams, remembers, persists across reload, separates threads', async ({ page }) => {
  await logIn(page)

  // Streaming: watch the assistant text grow across SSE deltas.
  await page.getByLabel('Message').fill('Count from 1 to 30 separated by commas.')
  await page.getByLabel('Message').press('Enter')
  const first = page.getByTestId('message-assistant').first()
  await expect(first).toContainText(/\d/, { timeout: 120_000 })
  const lengths = new Set<number>()
  while (await page.getByRole('button', { name: 'Stop' }).isVisible()) {
    lengths.add(((await first.textContent()) ?? '').length)
    await page.waitForTimeout(50)
  }
  expect(lengths.size).toBeGreaterThan(1)
  await expect(first).toContainText('30')

  // Memory within the thread.
  await ask(page, 'My name is Ada Lovelace. Just reply "Noted."')
  const recall = await ask(page, 'What is my name?')
  await expect(recall).toContainText(/Ada/i)

  // Thread appears in the sidebar, titled from the first message.
  const threadItems = page.getByTestId('thread-item')
  await expect(threadItems).toHaveCount(1)
  await expect(threadItems.first()).toContainText('Count from 1 to 30')
  const url = page.url()
  expect(url).toMatch(/\?t=/)

  // Reload keeps history.
  await page.reload()
  await expect(page.getByTestId('message-user')).toHaveCount(3)
  await expect(page.getByTestId('message-assistant')).toHaveCount(3)
  await expect(page.getByTestId('message-assistant').last()).toContainText(/Ada/i)

  // A second thread has its own history and no memory of the first.
  await page.getByRole('button', { name: 'New chat' }).click()
  await expect(page.getByText('How can I help?')).toBeVisible()
  await ask(page, 'Say hello in French, one word.')
  await expect(threadItems).toHaveCount(2)
  await expect(page.getByTestId('message-user')).toHaveCount(1)

  // Switching back shows the first thread's messages.
  await threadItems.filter({ hasText: 'Count from 1 to 30' }).click()
  await expect(page.getByTestId('message-user')).toHaveCount(3)
  await expect(page.getByTestId('message-user').nth(1)).toContainText('Ada Lovelace')
})

test('C.3/C.4: upload, grounded answer with source, delete, fact gone', async ({ page }) => {
  await logIn(page)

  // Upload via the Ingestion page.
  await page.getByRole('link', { name: 'Ingestion' }).click()
  await page.getByTestId('file-input').setInputFiles({
    name: 'project-notes.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from(
      'Internal project notes.\n\nThe secret project codename is ZEPHYR-42. ' +
        'It was chosen by the team lead Marisol Okonkwo in March.\n',
    ),
  })
  const row = page.getByTestId('document-row').filter({ hasText: 'project-notes.txt' })
  await expect(row.getByTestId('doc-status')).toHaveText('completed', { timeout: 60_000 })

  // Ask about it in Chat.
  await page.getByRole('link', { name: 'Chat' }).click()
  const answer = await ask(
    page,
    'Search my documents: what is the secret project codename, and who chose it?',
  )
  await expect(answer).toContainText(/zephyr.42/i)
  await expect(answer.getByTestId('sources')).toContainText('project-notes.txt')

  // Sources survive a reload.
  await page.reload()
  await expect(page.getByTestId('message-assistant').last().getByTestId('sources')).toContainText(
    'project-notes.txt',
  )

  // Delete the document.
  await page.getByRole('link', { name: 'Ingestion' }).click()
  await page.getByRole('button', { name: 'Delete project-notes.txt' }).click()
  await expect(page.getByTestId('document-row')).toHaveCount(0)
  await expect(page.getByText('No documents yet.')).toBeVisible()

  // New thread: the fact is gone.
  await page.getByRole('link', { name: 'Chat' }).click()
  await page.getByRole('button', { name: 'New chat' }).click()
  const after = await ask(page, 'What is the secret project codename in my documents?')
  await expect(after).not.toContainText(/zephyr.42/i)
  await expect(after.getByTestId('sources')).toHaveCount(0)
})

test('C.4: unsupported file type shows an error', async ({ page }) => {
  await logIn(page)
  await page.getByRole('link', { name: 'Ingestion' }).click()
  await page.getByTestId('file-input').setInputFiles({
    name: 'image.png',
    mimeType: 'image/png',
    buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47]),
  })
  await expect(page.getByRole('alert')).toContainText('unsupported type')
})
