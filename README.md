# Glossa

RAG app with a threaded chat (default view) and a document ingestion page.
Stack: React + Vite + Tailwind + shadcn/ui, FastAPI, Supabase, Google Gemini API, LangSmith.

```
backend/              FastAPI app (venv, requirements.txt, .env.example)
frontend/             Vite + React + TS + Tailwind + shadcn/ui (.env.example)
supabase/migrations/  SQL migrations (run in order)
```

## How it works

**Ingestion** (`backend/app/services/`): an upload is stored in Supabase Storage and
answered immediately; a background task then runs the pipeline and every status
change reaches the Documents page through Supabase Realtime.

| Step | File | What happens |
|------|------|--------------|
| Record manager | `record_manager.py` | File hash decides created / updated / unchanged / duplicate. On an update, chunk hashes decide which chunks are new: only those are embedded. |
| Parse | `parsing.py` | PDF, DOCX and HTML become Markdown via docling; `.md`/`.txt` are read as-is. |
| Chunk | `ingestion.py` | ~3200-char chunks with 400 overlap, split at headings, paragraphs, sentences. |
| Embed + store | `llm.py`, `db.py` | Gemini embeddings into pgvector (`document_chunks`). |
| Metadata | `metadata.py` | One structured LLM call fills `documents.metadata` (title, type, topics, summary...). |

**Chat** (`chat.py` -> `agent.py`): the API is stateless, so each turn sends the last
`CHAT_HISTORY_LIMIT` stored messages. The agent loop streams the model's answer and
runs any tools it asks for. Tools live in `services/tools/` and are listed in
`tools/registry.py`:

| Tool | When the model uses it | Backed by |
|------|------------------------|-----------|
| `file_search` | Questions about what documents say; optional type/topic/filename filters | `retrieval.py`: hybrid search (keyword + vector, RRF) in Postgres, then an LLM reranker |
| `analyze_document` | Whole-document tasks (summarise, extract everything) | `subagent.py`: a sub-agent with its own context and tools; only its answer comes back |
| `query_database` | Counts, lists, dates about the library | `execute_readonly_sql` RPC: one SELECT, run as the user under RLS |
| `web_search` | Fallback when documents lack the answer | Tavily; only offered when `TAVILY_API_KEY` is set |

Each tool call is streamed to the browser (`tool_call`, `tool_result`,
`subagent_delta`, `sources` SSE events), shown as a step timeline above the answer,
and saved with the message in `messages.steps`.

## Setup

### 1. Supabase (hosted)
1. Create a project at supabase.com.
2. Apply the migrations in `supabase/migrations/`, either way:
   - Put the database connection string in `backend/.env` as `SUPABASE_DB_URL`
     (**Connect -> Session pooler**) and run
     `backend/venv/bin/python backend/scripts/apply_migrations.py` (after step 2 below).
     It records what it applied in `public.schema_migrations`; `--status` lists them.
     On a database where `0001`-`0003` were already run by hand, its first run records
     those as done and applies the rest.
   - Or open **SQL Editor** and run each file in order (`0001` ... `0009`).
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

### 4. Run everything with one command
After filling in both `.env` files:
```bash
./start.sh          # backend on :8000 + frontend on :5173, Ctrl+C stops both
./start.sh --setup  # same, but (re)installs backend + frontend dependencies first
```
It creates the backend venv and runs `npm install` automatically if they're missing,
and refuses to start if a `.env` is missing or a port is busy. Override ports with
`BACKEND_PORT=8100 FRONTEND_PORT=5200 ./start.sh`.

## Lint / type check
Config lives in the root `pyproject.toml` (ruff + pyright, both aware of `backend/venv`).
```bash
ruff check . && ruff format --check .
```
In VS Code, select the interpreter `backend/venv/bin/python` (Python: Select Interpreter)
if Pylance still reports unresolved imports.

## Tests
```bash
cd backend
venv/bin/pytest -m "not integration"    # unit tests (no network)
venv/bin/pytest -m integration -v       # RLS, Storage, hybrid search and SQL RPC against your Supabase project
```
The integration tests read `backend/.env`, create two throwaway users with the
service-role key, check that neither can reach the other's rows, files or search
results, and delete them afterwards. They need every migration applied.

```bash
cd frontend
npm run build && npm run lint
npx playwright install chromium         # once
npm run test:e2e                        # everything below
npx playwright test e2e/agent-ui.spec.ts   # step timeline + Documents page, backend mocked (no model calls)
npx playwright test e2e/chat.spec.ts       # chat, memory, ingestion, tools, sub-agent (live Gemini API)
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

Each upload costs one embedding call per batch of new chunks plus one metadata call;
each `file_search` costs one embedding call plus one rerank call. On a free-tier key,
`RERANK_ENABLED=false` and `METADATA_EXTRACTION_ENABLED=false` save quota.

The first PDF upload after a backend start is slow: docling loads (and on the very
first run downloads) its layout models. `DOCUMENT_PARSER=basic` avoids that.
