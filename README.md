# Agentic RAG

RAG app with a threaded chat (default view) and a document ingestion page.
Stack: React + Vite + Tailwind + shadcn/ui, FastAPI, Supabase, OpenAI, LangSmith.

```
backend/              FastAPI app (venv, requirements.txt, .env.example)
frontend/             Vite + React + TS + Tailwind + shadcn/ui (.env.example)
supabase/migrations/  SQL migrations (run in order)
```

## Setup

### 1. Supabase (hosted)
1. Create a project at supabase.com.
2. Open **SQL Editor** and run `supabase/migrations/0001_init.sql`.
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
```
