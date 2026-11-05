# Progress

Track your progress through the masterclass. Update this file as you complete modules - Claude Code reads this to understand where you are in the project.

## Convention
- `[ ]` = Not started
- `[-]` = In progress
- `[x]` = Completed

## Modules

### Module 1: App Shell + Observability
Plan: `.agent/plans/1.module-1-app-shell.md`

- [-] **Phase A: Project setup + auth** (code complete; live checks waiting on Supabase credentials)
  - [x] A.1 Backend scaffold: FastAPI, venv (Python 3.14), CORS, `GET /health`, pydantic-settings config, `.env.example`
  - [-] A.2 Migration `supabase/migrations/0001_init.sql`: 4 tables with RLS. Checked against a local Postgres with a stubbed `auth` schema. Still to do: apply to the hosted project and run `pytest -m integration`
  - [x] A.3 `get_current_user` JWT dependency (HS256 secret or JWKS for ES256/RS256) + `GET /me`
  - [x] A.4 Frontend scaffold: Vite React TS, Tailwind v4, shadcn/ui (radix-nova), router, supabase-js, `lib/supabase.ts`, `lib/api.ts`
  - [-] A.5 Login (sign up / log in / errors), session listener, protected routes, nav (Chat `/`, Ingestion `/ingestion`), log out, header email fetched from `/me`. Still to do: browser validation with a real Supabase project
- [ ] Phase B: Chat with the Responses API
- [ ] Phase C: Minimal document upload
- [ ] Phase D: LangSmith tracing
