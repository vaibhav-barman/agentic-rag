import { expect, test, type Page, type Route } from '@playwright/test'

import { createConfirmedUser, deleteUser, type TestUser } from './supabaseAdmin'

// UI tests for the agent step timeline, nested sub-agent display, web sources and the
// Documents page. Auth is real (Supabase); the backend API is mocked, so these run
// without a model, without quota, and with deterministic content.

const API = 'http://localhost:8000'
const SHOTS = process.env.SCREENSHOT_DIR

let user: TestUser

test.beforeAll(async () => {
  user = await createConfirmedUser()
})

test.afterAll(async () => {
  if (user) await deleteUser(user.id)
})

const sse = (events: [string, unknown][]) =>
  events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('')

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

const STEPS = [
  {
    id: 's1',
    name: 'file_search',
    arguments: { query: 'handbook onboarding', document_type: 'manual' },
    parent_id: null,
    ok: true,
    summary: '2 passages from handbook.md',
    data: {
      filters: { document_type: 'manual' },
      results: [
        { filename: 'handbook.md', passage: 0, score: 0.92, vector_rank: 1, keyword_rank: 2 },
        { filename: 'handbook.md', passage: 4, score: 0.41, vector_rank: 3, keyword_rank: null },
      ],
    },
  },
  {
    id: 's2',
    name: 'analyze_document',
    arguments: { document_id: 'd1', task: 'Summarise the whole handbook, start to finish.' },
    parent_id: null,
    ok: true,
    summary: 'Read handbook.md (48,210 characters)',
    data: { document: 'handbook.md', characters: 48210, truncated: false },
    text: 'The handbook covers **onboarding**, leave policy and ends with the ZEBRA clause.',
  },
  {
    id: 's3',
    name: 'read_passages',
    arguments: { start: 10, end: 12 },
    parent_id: 's2',
    ok: true,
    summary: 'Read passages 10-12',
    data: null,
  },
  {
    id: 's4',
    name: 'query_database',
    arguments: { sql: 'select count(*) as documents from documents' },
    parent_id: null,
    ok: true,
    summary: '1 row',
    data: {
      sql: 'select count(*) as documents from documents',
      columns: ['documents'],
      rows: [{ documents: 3 }],
      row_count: 1,
    },
  },
  {
    id: 's5',
    name: 'web_search',
    arguments: { query: 'zebra clause meaning' },
    parent_id: null,
    ok: false,
    summary: 'Web search failed',
    data: null,
  },
]

const SOURCES = [
  { type: 'document', document_id: 'd1', filename: 'handbook.md', chunk_index: 0, content: 'Onboarding takes two weeks.', score: 0.92 },
  { type: 'web', title: 'Zebra clauses explained', url: 'https://example.com/zebra', content: 'A zebra clause is a made-up thing.', score: 0.8 },
]

const ANSWER = 'Your handbook covers onboarding and ends with the ZEBRA clause. You have 3 documents.'

async function mockApi(page: Page) {
  const thread = { id: 't1', title: 'Summarise my handbook', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }
  let stored: unknown[] = []
  await page.route(`${API}/me`, (route) => json(route, { id: user.id, email: user.email }))
  await page.route(`${API}/threads`, (route) =>
    route.request().method() === 'POST' ? json(route, thread, 201) : json(route, stored.length ? [thread] : []),
  )
  await page.route(`${API}/threads/t1/messages`, (route) => json(route, stored))
  await page.route(`${API}/threads/t1/chat`, async (route) => {
    const [search, agent, read, sql, web] = STEPS
    const call = ({ id, name, arguments: args, parent_id }: (typeof STEPS)[number]) => ['tool_call', { id, name, arguments: args, parent_id }] as [string, unknown]
    const result = ({ id, ok, summary, data, parent_id }: (typeof STEPS)[number]) => ['tool_result', { id, ok, summary, data, parent_id }] as [string, unknown]
    const body = sse([
      ['user_message', { id: 'u1' }],
      call(search),
      result(search),
      ['sources', { query: 'handbook onboarding', sources: [SOURCES[0]] }],
      call(agent),
      call(read),
      result(read),
      ['subagent_delta', { parent_id: 's2', text: 'The handbook covers **onboarding**, leave policy ' }],
      ['subagent_delta', { parent_id: 's2', text: 'and ends with the ZEBRA clause.' }],
      result(agent),
      call(sql),
      result(sql),
      call(web),
      result(web),
      ['sources', { query: 'zebra clause meaning', sources: [SOURCES[1]] }],
      ['delta', { text: ANSWER }],
      ['done', { message_id: 'a1', title: thread.title }],
    ])
    stored = [
      { id: 'u1', role: 'user', content: 'Summarise my handbook', created_at: '2026-01-01T00:00:00Z' },
      { id: 'a1', role: 'assistant', content: ANSWER, sources: SOURCES, steps: STEPS, created_at: '2026-01-01T00:00:01Z' },
    ]
    await route.fulfill({ status: 200, contentType: 'text/event-stream', body })
  })
}

async function logIn(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(user.email)
  await page.getByLabel('Password').fill(user.password)
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByText('How can I help?')).toBeVisible()
}

async function expectSteps(page: Page) {
  const answer = page.getByTestId('message-assistant').last()
  const top = answer.getByTestId('tool-steps').locator('> li')
  await expect(top).toHaveCount(4)
  await expect(top.nth(0)).toContainText('Searched your documents')
  await expect(top.nth(0)).toContainText('2 passages from handbook.md')

  // Module 8: the sub-agent's own step and text are nested inside its parent step.
  const subagent = top.nth(1).getByTestId('subagent')
  await expect(subagent).toBeVisible()
  await expect(subagent).toContainText('separate context')
  await expect(subagent).toContainText('Summarise the whole handbook, start to finish.')
  await expect(subagent.getByTestId('tool-step')).toHaveCount(1)
  await expect(subagent.getByTestId('tool-step')).toHaveText('Read passages 10–12')
  await expect(subagent.getByTestId('subagent-text')).toContainText('ends with the ZEBRA clause')
  // ...and the sub-agent's text is not part of the main answer.
  await expect(answer.locator('.prose-chat').last()).toHaveText(ANSWER)

  // Module 7: SQL step shows the query and its rows when opened.
  await top.nth(2).locator('summary').click()
  await expect(top.nth(2).getByTestId('sql-query')).toHaveText('select count(*) as documents from documents')
  await expect(top.nth(2).getByTestId('sql-rows')).toContainText('3')
  await expect(top.nth(3)).toHaveAttribute('data-status', 'failed')
  await expect(top.nth(3)).toContainText('Web search failed')

  // Attribution: a file note and a linked web page.
  const sources = answer.getByTestId('sources')
  await expect(sources).toContainText('handbook.md')
  await expect(sources.getByRole('link', { name: 'Zebra clauses explained' })).toHaveAttribute('href', 'https://example.com/zebra')
}

test('steps, nested sub-agent and sources render while streaming and after reload', async ({ page }) => {
  await mockApi(page)
  await logIn(page)
  await page.getByLabel('Message').fill('Summarise my handbook')
  await page.getByLabel('Message').press('Enter')
  await expect(page.getByRole('button', { name: 'Stop' })).toBeHidden()
  await expectSteps(page)
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/chat-steps.png`, fullPage: true })

  await page.reload()
  await expect(page.getByTestId('message-assistant')).toHaveCount(1)
  await expectSteps(page)

  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(400) // let the sidebar finish sliding away
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/chat-steps-mobile.png`, fullPage: true })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  expect(overflow).toBe(false)
})

test('documents page shows status, metadata, reuse stats and the dedup toast', async ({ page }) => {
  const base = { error: null, file_size: 20480, ingest_stats: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }
  const done = {
    ...base,
    id: 'd1',
    filename: 'handbook.md',
    status: 'completed',
    chunk_count: 9,
    ingest_stats: { embedded: 2, reused: 7, removed: 2 },
    metadata: { title: 'Handbook', summary: 'How the company onboards people.', document_type: 'manual', topics: ['onboarding', 'leave'] },
  }
  const docs = [
    done,
    { ...base, id: 'd2', filename: 'scan.pdf', status: 'processing', chunk_count: 0, metadata: {} },
    { ...base, id: 'd3', filename: 'broken.docx', status: 'failed', error: 'Could not read DOCX file: not a zip', chunk_count: 0, metadata: {} },
  ]
  await page.route(`${API}/me`, (route) => json(route, { id: user.id, email: user.email }))
  await page.route(`${API}/threads`, (route) => json(route, []))
  await page.route(`${API}/documents`, (route) =>
    route.request().method() === 'POST' ? json(route, { ...done, action: 'unchanged' }) : json(route, docs),
  )
  await logIn(page)
  await page.getByRole('link', { name: 'Documents' }).click()

  const rows = page.getByTestId('document-row')
  await expect(rows).toHaveCount(3)
  await expect(rows.nth(0).getByTestId('doc-status')).toHaveText('completed')
  await expect(rows.nth(0).getByTestId('doc-detail')).toContainText('9 passages · 2 new, 7 reused')
  await expect(rows.nth(0).getByTestId('doc-metadata')).toContainText('manual')
  await expect(rows.nth(0).getByTestId('doc-metadata')).toContainText('onboarding')
  await expect(rows.nth(0)).toContainText('How the company onboards people.')
  await expect(rows.nth(1).getByTestId('doc-status')).toHaveText('processing')
  await expect(rows.nth(2)).toContainText('Could not read DOCX file')

  // Module 3: re-uploading unchanged content tells the user nothing was re-processed.
  await page.getByTestId('file-input').setInputFiles({ name: 'handbook.md', mimeType: 'text/markdown', buffer: Buffer.from('# Handbook') })
  await expect(page.getByText('handbook.md is already up to date')).toBeVisible()
  await expect(rows).toHaveCount(3)
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/documents.png`, fullPage: true })

  // New formats are accepted client-side; others are still refused.
  await page.getByTestId('file-input').setInputFiles({ name: 'image.png', mimeType: 'image/png', buffer: Buffer.from([0x89]) })
  await expect(page.getByRole('alert')).toContainText('unsupported type')
})
