-- Module 1 with a stateless LLM API: the app owns memory and retrieval.
-- Additive only. The OpenAI-era leftovers - threads.last_response_id,
-- documents.openai_file_id and the user_vector_stores table - are no longer used
-- by the app and stay in place, still protected by RLS.

alter table public.threads add column if not exists updated_at timestamptz not null default now();
create index if not exists threads_user_updated_idx on public.threads (user_id, updated_at desc);

alter table public.documents add column if not exists error text;
alter table public.documents add column if not exists chunk_count int not null default 0;

-- Sources (file_search hits) shown under assistant answers.
alter table public.messages add column if not exists sources jsonb;
