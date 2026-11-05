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
