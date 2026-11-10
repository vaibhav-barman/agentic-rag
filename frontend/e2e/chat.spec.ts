import { readFileSync } from 'node:fs'
import path from 'node:path'

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

  // Streaming: the server sends the answer as several SSE delta events.
  const chatResponse = page.waitForResponse((r) => /\/threads\/[^/]+\/chat$/.test(r.url()))
  await page.getByLabel('Message').fill('Count from 1 to 30 separated by commas.')
  await page.getByLabel('Message').press('Enter')
  const response = await chatResponse
  expect(response.headers()['content-type']).toContain('text/event-stream')
  const sseBody = await response.text()
  expect(sseBody.match(/^event: delta$/gm)?.length ?? 0).toBeGreaterThan(1)
  expect(sseBody).toContain('event: done')
  const first = page.getByTestId('message-assistant').first()
  await expect(first).toContainText('30', { timeout: 120_000 })
  await expect(page.getByRole('button', { name: 'Stop' })).toBeHidden({ timeout: 120_000 })

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

  // Upload via the Documents page.
  await page.getByRole('link', { name: 'Documents' }).click()
  await page.getByTestId('file-input').setInputFiles({
    name: 'project-notes.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from(
      'Internal project notes.\n\nThe secret project codename is ZEPHYR-42. ' +
        'It was chosen by the team lead Marisol Okonkwo in March.\n',
    ),
  })
  const row = page.getByTestId('document-row').filter({ hasText: 'project-notes.txt' })
  await expect(row.getByTestId('doc-status')).toHaveText('completed', { timeout: 90_000 })

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
  await page.getByRole('link', { name: 'Documents' }).click()
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
  await page.getByRole('link', { name: 'Documents' }).click()
  await page.getByTestId('file-input').setInputFiles({
    name: 'image.png',
    mimeType: 'image/png',
    buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47]),
  })
  await expect(page.getByRole('alert')).toContainText('unsupported type')
})

// --- Modules 2-8 (live) -------------------------------------------------------

async function uploadFile(page: Page, name: string, mimeType: string, buffer: Buffer) {
  await page.getByTestId('file-input').setInputFiles({ name, mimeType, buffer })
  const row = page.getByTestId('document-row').filter({ hasText: name })
  await expect(row).toBeVisible({ timeout: 30_000 })
  return row
}

test('M2/M3/M4: status arrives over Realtime, metadata is shown, re-upload is skipped', async ({ page }) => {
  await logIn(page)
  await page.getByRole('link', { name: 'Documents' }).click()
  await expect(page.getByTestId('live-status')).toContainText('Live status updates', { timeout: 20_000 })

  // After the upload request, the page must not fetch the list again: every status
  // change has to come through the Realtime subscription.
  let refetches = 0
  let uploaded = false
  page.on('request', (r) => {
    if (uploaded && r.method() === 'GET' && r.url().endsWith('/documents')) refetches += 1
  })
  const body = Buffer.from(
    '# Greenhouse maintenance manual\n\nWater the tomato beds every second day. ' +
      'Replace the irrigation filter with part number GH-5520-T each spring.\n',
  )
  const posted = page.waitForResponse((r) => r.url().endsWith('/documents') && r.request().method() === 'POST')
  const row = await uploadFile(page, 'greenhouse-manual.md', 'text/markdown', body)
  const response = await posted
  uploaded = true
  expect(response.status()).toBe(201)
  expect((await response.json()).status).toBe('pending') // ingestion happens after the response

  await expect(row.getByTestId('doc-status')).toHaveText('completed', { timeout: 90_000 })
  expect(refetches).toBe(0)
  await expect(row.getByTestId('doc-detail')).toContainText('1 passage')
  // Module 4: extracted metadata (a type badge at least) appears on the row.
  await expect(row.getByTestId('doc-metadata')).toBeVisible()

  // Module 3: the same bytes again are recognised and not re-processed.
  await page.getByTestId('file-input').setInputFiles({ name: 'greenhouse-manual.md', mimeType: 'text/markdown', buffer: body })
  await expect(page.getByText('greenhouse-manual.md is already up to date')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('document-row')).toHaveCount(1)

  // Module 6: an exact part number is found (keyword leg of hybrid search).
  await page.getByRole('link', { name: 'Chat' }).click()
  const answer = await ask(page, 'Search my documents: which part number is the irrigation filter?')
  await expect(answer).toContainText('GH-5520-T')
  await expect(answer.getByTestId('tool-step').first()).toHaveAttribute('data-tool', 'file_search')
  await expect(answer.getByTestId('sources')).toContainText('greenhouse-manual.md')
})

test('M5/M7/M8: DOCX and HTML ingest, SQL tool counts, sub-agent reads a whole document', async ({ page }) => {
  await logIn(page)
  await page.getByRole('link', { name: 'Documents' }).click()

  const docx = await uploadFile(
    page,
    'orchard-plan.docx',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    readFileSync(path.resolve(import.meta.dirname, 'fixtures/orchard-plan.docx')),
  )
  const html = await uploadFile(
    page,
    'pricing.html',
    'text/html',
    Buffer.from('<html><body><h1>Pricing</h1><p>The Harbour plan costs 42 dollars per seat.</p></body></html>'),
  )
  // The first DOCX can take a while: docling loads on first use.
  await expect(docx.getByTestId('doc-status')).toHaveText('completed', { timeout: 150_000 })
  await expect(html.getByTestId('doc-status')).toHaveText('completed', { timeout: 150_000 })

  await page.getByRole('link', { name: 'Chat' }).click()

  // Module 5: a fact that only exists inside the DOCX.
  const fromDocx = await ask(page, 'Search my documents: who is the budget owner of the Orchard project?')
  await expect(fromDocx).toContainText(/Priya Raman/i)

  // Module 7: a question about the library as data goes to SQL.
  const counted = await ask(page, 'Use the database to count how many documents I have uploaded in total.')
  const sqlStep = counted.locator('[data-testid="tool-step"][data-tool="query_database"]').first()
  await expect(sqlStep).toHaveAttribute('data-status', 'ok')
  await sqlStep.locator('summary').click()
  await expect(sqlStep.getByTestId('sql-query')).toContainText(/select/i)
  await expect(counted.locator('.prose-chat').last()).toContainText(/\b(2|two)\b/i)

  // Module 8: a whole-document task is delegated to a sub-agent, shown nested.
  const summary = await ask(
    page,
    'Read the whole orchard-plan.docx with the sub-agent and give me a full summary, including its closing note.',
  )
  const subagent = summary.getByTestId('subagent').first()
  await expect(subagent).toBeVisible()
  await expect(subagent.getByTestId('subagent-text')).not.toBeEmpty()
  // Content from the start and from the very end of the document.
  await expect(summary).toContainText(/Orchard/i)
  await expect(summary).toContainText(/MARIGOLD-77/i)

  // The nested view survives a reload (steps are stored with the message).
  await page.reload()
  await expect(page.getByTestId('message-assistant').last().getByTestId('subagent')).toBeVisible()
})
