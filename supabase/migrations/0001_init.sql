-- Module 1 schema: threads, messages, per-user OpenAI vector store, documents.
-- Every table has RLS: a user can only see and modify rows where user_id = auth.uid().

-- ---------------------------------------------------------------------------
-- threads
-- ---------------------------------------------------------------------------
create table if not exists public.threads (
    id               uuid primary key default gen_random_uuid(),
    user_id          uuid not null default auth.uid() references auth.users (id) on delete cascade,
    title            text,
    last_response_id text,  -- OpenAI Responses API id used as previous_response_id (Module 1 only)
    created_at       timestamptz not null default now()
);
create index if not exists threads_user_created_idx on public.threads (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- messages (stored for display; model memory comes from previous_response_id)
-- ---------------------------------------------------------------------------
create table if not exists public.messages (
    id         uuid primary key default gen_random_uuid(),
    thread_id  uuid not null references public.threads (id) on delete cascade,
    user_id    uuid not null default auth.uid() references auth.users (id) on delete cascade,
    role       text not null check (role in ('user', 'assistant')),
    content    text not null,
    created_at timestamptz not null default now()
);
create index if not exists messages_thread_created_idx on public.messages (thread_id, created_at);

-- ---------------------------------------------------------------------------
-- user_vector_stores (one OpenAI vector store per user; Module 1 only)
-- ---------------------------------------------------------------------------
create table if not exists public.user_vector_stores (
    user_id         uuid primary key default auth.uid() references auth.users (id) on delete cascade,
    vector_store_id text not null,
    created_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- documents
-- ---------------------------------------------------------------------------
create table if not exists public.documents (
    id             uuid primary key default gen_random_uuid(),
    user_id        uuid not null default auth.uid() references auth.users (id) on delete cascade,
    filename       text not null,
    openai_file_id text,  -- Module 1 only
    status         text not null default 'processing'
                   check (status in ('processing', 'completed', 'failed')),
    created_at     timestamptz not null default now()
);
create index if not exists documents_user_created_idx on public.documents (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- Row-Level Security
-- ---------------------------------------------------------------------------
alter table public.threads            enable row level security;
alter table public.messages           enable row level security;
alter table public.user_vector_stores enable row level security;
alter table public.documents          enable row level security;

-- threads
create policy "threads_select_own" on public.threads
    for select to authenticated using ((select auth.uid()) = user_id);
create policy "threads_insert_own" on public.threads
    for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "threads_update_own" on public.threads
    for update to authenticated
    using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "threads_delete_own" on public.threads
    for delete to authenticated using ((select auth.uid()) = user_id);

-- messages: own rows only, and inserts must target a thread the user owns
create policy "messages_select_own" on public.messages
    for select to authenticated using ((select auth.uid()) = user_id);
create policy "messages_insert_own" on public.messages
    for insert to authenticated with check (
        (select auth.uid()) = user_id
        and exists (
            select 1 from public.threads t
            where t.id = thread_id and t.user_id = (select auth.uid())
        )
    );
create policy "messages_update_own" on public.messages
    for update to authenticated
    using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "messages_delete_own" on public.messages
    for delete to authenticated using ((select auth.uid()) = user_id);

-- user_vector_stores
create policy "user_vector_stores_select_own" on public.user_vector_stores
    for select to authenticated using ((select auth.uid()) = user_id);
create policy "user_vector_stores_insert_own" on public.user_vector_stores
    for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "user_vector_stores_update_own" on public.user_vector_stores
    for update to authenticated
    using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "user_vector_stores_delete_own" on public.user_vector_stores
    for delete to authenticated using ((select auth.uid()) = user_id);

-- documents
create policy "documents_select_own" on public.documents
    for select to authenticated using ((select auth.uid()) = user_id);
create policy "documents_insert_own" on public.documents
    for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "documents_update_own" on public.documents
    for update to authenticated
    using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "documents_delete_own" on public.documents
    for delete to authenticated using ((select auth.uid()) = user_id);
