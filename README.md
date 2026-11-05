# Agentic RAG

RAG app with a threaded chat (default view) and a document ingestion page.
Stack: React + Vite + Tailwind + shadcn/ui, FastAPI, Supabase, Google Gemini API, LangSmith.

```
backend/              FastAPI app (venv, requirements.txt, .env.example)
frontend/             Vite + React + TS + Tailwind + shadcn/ui (.env.example)
supabase/migrations/  SQL migrations (run in order)
```

## Setup

### 1. Supabase (hosted)
1. Create a project at supabase.com.
2. Open **SQL Editor** and run each file in `supabase/migrations/` in order
   (`0001_init.sql`, `0002_app_managed_chat.sql`, `0003_document_chunks.sql`).
3. Under **Authentication → Providers → Email**, keep email enabled. For local dev you
   can turn off "Confirm email" so sign-up logs you straight in.
4. From **Project Settings → API keys** copy the URL, anon (publishable) key and
   service-role (secret) key. If your project still uses the legacy JWT secret,
   copy it from **JWT Keys**; otherwise leave `SUPABASE_JWT_SECRET` empty and the
   backend verifies tokens via the project's JWKS endpoint.

### 2. Backend
```bash
cd backend
python3.14 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env        # fill in values
venv/bin/uvicorn app.main:app --reload --port 8000
```

### 3. Frontend
```bash
cd frontend
npm install
cp .env.example .env        # fill in values
npm run dev                 # http://localhost:5173
```

## Tests
```bash
cd backend
venv/bin/pytest                         # unit tests (no network)
venv/bin/pytest -m integration -v       # RLS cross-user test against your Supabase project
```
The integration test reads `backend/.env`, creates two throwaway users with the
service-role key, checks that neither can read or write the other's rows, and
deletes them afterwards.

```bash
cd frontend
npm run build && npm run lint
npx playwright install chromium         # once
npm run test:e2e                        # auth, chat, memory, upload + file search (live Gemini API)
```
The e2e suite creates a confirmed throwaway user with the service-role key from
`backend/.env` (no email is sent) and deletes it afterwards. Sign-up responses are
mocked so no confirmation emails go out.

## Models
Set in `backend/.env` (`GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_EMBEDDING_MODEL`).
Get a key at https://aistudio.google.com/apikey. The chat model must support tool
calling; `gemini-embedding-001` is shortened to 1024 dims to match the database.
Switching embedding models later means re-uploading documents (vectors from different
models aren't comparable).
