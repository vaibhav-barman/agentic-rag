# Progress

Track your progress through the masterclass. Update this file as you complete modules - Claude Code reads this to understand where you are in the project.

## Convention
- `[ ]` = Not started
- `[-]` = In progress
- `[x]` = Completed

## Modules

### Module 1: App Shell + Observability
Plan: `.agent/plans/1.module-1-app-shell.md`

- [x] **Phase A: Project setup + auth**
  - [x] A.1 Backend scaffold: FastAPI, venv (Python 3.14), CORS, `GET /health`, pydantic-settings config, `.env.example`
  - [x] A.2 Migration `supabase/migrations/0001_init.sql` applied to the hosted project; RLS cross-user test (`pytest -m integration`) 3/3 pass
  - [x] A.3 `get_current_user` JWT dependency (HS256 secret or JWKS for ES256/RS256; project uses ES256) + `GET /me`
  - [x] A.4 Frontend scaffold: Vite React TS, Tailwind v4, shadcn/ui (radix-nova), router, supabase-js, `lib/supabase.ts`, `lib/api.ts`
  - [x] A.5 Login/sign-up, session listener, protected routes, nav, log out, `/me` email in header. Playwright e2e (`npm run test:e2e`) 7/7 pass
- LLM provider: Google Gemini API via its OpenAI-compatible endpoint. Phases B-D planned in `.agent/plans/2.module-1-chat-file-search.md`
- [x] **Phase B: Threads + memory + streaming chat**
  - [x] B.1 Migration `0002_app_managed_chat.sql` (additive: `threads.updated_at`, `documents.error/chunk_count`, `messages.sources`); applied
  - [x] B.2 Per-request Supabase client with the user's JWT (`app/db.py`), so RLS applies to every query
  - [x] B.3 `POST/GET/DELETE /threads`, `GET /threads/{id}/messages`; foreign thread -> 404
  - [x] B.4 `POST /threads/{id}/chat` SSE (`user_message`, `delta`, `sources`, `done`, `error`); last 20 messages sent as memory; title from first message
  - [x] B.5 Chat UI: thread sidebar (new/select/delete), streaming Markdown, stop button, `?t=<id>` keeps the thread on reload
- [x] **Phase C: Upload + file_search tool (pgvector)**
  - [x] C.1 Migration `0003_document_chunks.sql`: `document_chunks` vector(1024) + HNSW + RLS, `match_document_chunks` RPC (security invoker); applied
  - [x] C.2 `POST/GET/DELETE /documents`: .txt/.md/.pdf, 10 MB cap, chunk (3200/400 chars) -> embed -> store; status completed/failed
  - [x] C.3 `file_search` tool offered when the user has documents; sources shown as chips and saved with the message; Gemini `thought_signature` echoed back with tool calls
  - [x] C.4 Ingestion UI: drag-and-drop/browse, status badges, delete
- [x] **Phase D: LangSmith tracing**: `@traceable` `chat_turn` (metadata `user_id`, `thread_id`, `file_search_enabled/used`, model) with child `gemini_chat` llm runs (token usage) and `gemini_embed` runs; trace inputs exclude the user's token. (`wrap_openai` is not used: it crashes on Gemini's index-less streamed tool calls.)

**Module 1 complete.** Tests: backend 41/41 (incl. hosted RLS + chunk isolation), Playwright e2e 10/10 (live Gemini).
Models (set in `backend/.env`): chat `gemini-flash-lite-latest`, embeddings `gemini-embedding-001` (1024 dims). Free tier quotas are per model per day; re-upload documents after switching embedding models.

---

## Modules 2-8
Plan: `.agent/plans/3.modules-2-8.md`. Branch: `modules-2-8`.

**State:** all seven modules are built, unit-tested and browser-tested with a mocked
backend. **Not yet done:** migrations `0004`-`0009` are not applied to the hosted
database, so nothing below has been validated live. Each module is therefore `[-]`
until its "Live validation" line is ticked.

**To finish:**
1. Apply migrations `0004`-`0009`. Either add `SUPABASE_DB_URL` to `backend/.env` and run
   `backend/venv/bin/python backend/scripts/apply_migrations.py`, or run
   `backend/venv/bin/python backend/scripts/apply_migrations.py --sql 0004` and paste the output into the Supabase SQL Editor.
   Until this is done the Documents page and chat show "The database is missing migrations" (the code expects the new columns).
2. `cd backend && venv/bin/pytest -m integration -v`
3. `cd frontend && npx playwright test e2e/chat.spec.ts` (live Gemini)
4. Optional: add `TAVILY_API_KEY` and ask a current-events question to validate web search live.
5. Re-upload documents ingested during Module 1 (they have no hash, metadata or stored full text).

Decisions: Option A (managed-RAG schema dropped); Gemini as reranker; Tavily for web
search; docling for parsing (installs and runs on Python 3.14; basic parsers kept as
fallback); text-to-SQL queries the user's own library tables.

### Module 2: BYO Retrieval + Memory
- [-] **Module 2**
  - [x] 2.1 Migration `0004_byo_retrieval.sql` written: Option A cleanup, `documents` storage/status columns, private `documents` Storage bucket with per-user policies, Realtime publication, `match_document_chunks` threshold, `messages.steps`
  - [x] 2.2 `scripts/apply_migrations.py` (psycopg, `public.schema_migrations`, baselines `0001`-`0003`)
  - [x] 2.3 `POST /documents` stores the file in Storage and returns `pending`; `process_document` runs in the background; delete removes the stored file (pytest)
  - [x] 2.4 Documents page subscribes to Realtime (`postgres_changes`), with a polling fallback only when the socket is down
  - [x] 2.5 Stateless chat memory: last `CHAT_HISTORY_LIMIT` stored messages sent each turn (unchanged from Module 1; pytest)
  - [ ] Live validation: migration applied; integration tests for Storage isolation; Playwright "status arrives over Realtime with no refetch"

### Module 3: Record Manager
- [-] **Module 3**
  - [x] 3.1 Migration `0005_record_manager.sql` written: `content_hash` on documents and chunks, `ingest_stats`, unique `(user_id, filename)`
  - [x] 3.2 `record_manager.decide()`: created / updated / unchanged / duplicate (pytest: same file twice embeds once; same bytes under another name is a duplicate; failed upload can be retried)
  - [x] 3.3 `plan_chunks()`: chunk-hash diff so only new chunks are embedded, moved ones re-indexed, stale ones deleted (pytest: append embeds 1 chunk, rewrite replaces only the changed chunk)
  - [x] 3.4 UI: "already up to date" / "same content as" toasts, "n new, n reused" on the row (Playwright, mocked API)
  - [ ] Live validation: Playwright re-upload against the hosted database

### Module 4: Metadata Extraction
- [-] **Module 4**
  - [x] 4.1 Migration `0006_metadata.sql` written: `documents.metadata` jsonb + GIN, RPC `filter` / `filename_filter` / `document_id_filter`
  - [x] 4.2 `DocumentMetadata` Pydantic model + `llm.complete_structured()` (checked live against Gemini: structured output parses)
  - [x] 4.3 Extraction during ingestion, non-fatal on failure (pytest)
  - [x] 4.4 `file_search` accepts `document_type`, `topic`, `filename`; retries unfiltered if the filter matches nothing (pytest)
  - [x] 4.5 UI: type badge, topics, summary on each document (Playwright, mocked API)
  - [ ] Live validation: integration test for the RPC filters; live filtered question

### Module 5: Multi-Format Support
- [-] **Module 5**
  - [x] 5.1 `parsing.parse_document()`: PDF/DOCX/HTML via docling, `.md`/`.txt` read directly (deviation from plan: Markdown is not passed through docling, it is already Markdown); basic parsers as `DOCUMENT_PARSER=basic` and automatic fallback (pytest for both parsers; docling checked on a real text PDF)
  - [x] 5.2 Chunker prefers Markdown heading boundaries (pytest)
  - [x] 5.3 Cascade deletes: chunks, stored text and the Storage object go with the document (pytest with fakes)
  - [ ] Live validation: Playwright DOCX + HTML upload and a question answered from the DOCX; integration test for cascade on the hosted database

### Module 6: Hybrid Search & Reranking
- [-] **Module 6**
  - [x] 6.1 Migration `0007_hybrid_search.sql` written: `fts` tsvector column + GIN, `hybrid_search_chunks` RPC (keyword + vector legs, RRF, `search_mode`)
  - [x] 6.2 `retrieval.search()` with `SEARCH_MODE`, `RETRIEVAL_CANDIDATES`, similarity threshold in vector mode (pytest)
  - [x] 6.3 LLM reranker with `RERANK_MIN_SCORE`, falls back to fused order on failure (pytest; structured rerank output checked live against Gemini)
  - [ ] Live validation: integration test (exact token `XK-7741-Q` found by the keyword leg, RLS on the RPC); live exact-code question

### Module 7: Additional Tools
- [-] **Module 7**
  - [x] 7.1 Migration `0008_readonly_sql.sql` written: `execute_readonly_sql` (security invoker, single SELECT, public schema only, read-only transaction, 5s timeout, 100 rows)
  - [x] 7.2 Tool interface + registry + shared agent loop (`services/agent.py`, `services/tools/`); steps saved in `messages.steps` (pytest)
  - [x] 7.3 `query_database` tool with Python-side validation (pytest: writes, multi-statement, other schemas refused; rows trimmed)
  - [x] 7.4 `web_search` tool via Tavily, offered only when `TAVILY_API_KEY` is set, web sources with URLs (pytest with a mocked HTTP transport)
  - [x] 7.5 UI: step timeline with SQL + rows, search ranks, failed steps, linked web sources (Playwright, mocked API)
  - [ ] Live validation: integration test for the SQL RPC under RLS; live count question; live web search (needs `TAVILY_API_KEY`)

### Module 8: Sub-Agents
- [-] **Module 8**
  - [x] 8.1 Migration `0009_document_contents.sql` written: full parsed text per document, RLS, cascade
  - [x] 8.2 `analyze_document` tool + `subagent.py`: isolated context (document + task only), own tools `search_in_document` / `read_passages`, only the answer returns (pytest proves the chat history does not reach the sub-agent and the document does not reach the main agent)
  - [x] 8.3 Events carry `parent_id`; nested steps and sub-agent text persisted (pytest)
  - [x] 8.4 UI: nested sub-agent block with its steps and streamed text, live and after reload, desktop and phone width (Playwright, mocked API)
  - [ ] Live validation: Playwright whole-document summary; `chat_turn -> sub_agent` trace in LangSmith
  - Not built: model "thinking" text. Gemini's OpenAI-compatible endpoint returns only an opaque `thought_signature`, no thought summaries (probed live), so "reasoning" is shown as the step timeline plus the sub-agent's streamed text.

### After the modules
- [x] Database errors return JSON with CORS headers. An un-migrated database used to show only "Failed to fetch" in the browser; it now says the migrations are missing and how to run them (pytest)
- [x] `apply_migrations.py --sql` prints a paste-ready script for the SQL Editor
- [x] Frontend redesign: black and warm-white themes with a remembered toggle, verdigris as the only colour, Geist + Newsreader, starter prompts on the empty chat, phone-width overflow fixed (Playwright, mocked API, both themes checked by screenshot)
- [x] README rewritten (quick start, architecture, tools, configuration, migrations, troubleshooting)

**Tests now:** backend unit 80/80 (`pytest -m "not integration"`), ruff + pyright clean, frontend build + lint clean, Playwright `agent-ui.spec.ts` 2/2 and `auth.spec.ts` 7/7.
**Written but not run** (need the migrations): 6 new integration tests in `tests/test_rls.py`, 2 new live tests in `e2e/chat.spec.ts`.
