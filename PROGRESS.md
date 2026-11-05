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
- LLM provider switched to OpenRouter (`OPENROUTER_*` env vars). Phases B/C need replanning: OpenRouter has no `previous_response_id` memory or hosted vector stores / `file_search`
- [ ] Phase B: Chat with the Responses API
- [ ] Phase C: Minimal document upload
- [ ] Phase D: LangSmith tracing
