-- Module 2: bring-your-own retrieval.
-- 1. Option A cleanup: remove the schema left over from the managed (Responses API) era.
-- 2. Files live in Supabase Storage; ingestion is asynchronous and reports status via Realtime.
-- 3. Retrieval gets a relevance threshold.

-- ---------------------------------------------------------------------------
-- 1. Cleanup
-- ---------------------------------------------------------------------------
alter table public.threads   drop column if exists last_response_id;
alter table public.documents drop column if exists openai_file_id;
drop table if exists public.user_vector_stores;

-- ---------------------------------------------------------------------------
-- 2. Documents: storage location + async status
-- ---------------------------------------------------------------------------
alter table public.documents add column if not exists storage_path text;
alter table public.documents add column if not exists file_size bigint;
alter table public.documents add column if not exists mime_type text;
alter table public.documents add column if not exists updated_at timestamptz not null default now();

alter table public.documents drop constraint if exists documents_status_check;
alter table public.documents add constraint documents_status_check
    check (status in ('pending', 'processing', 'completed', 'failed'));
alter table public.documents alter column status set default 'pending';

-- Tool-step trace shown with assistant answers (used from Module 7 on).
alter table public.messages add column if not exists steps jsonb;

-- Private bucket. Objects are stored under "<user id>/<document id>/...", and
-- the first path segment is what the policies check.
insert into storage.buckets (id, name, public)
values ('documents', 'documents', false)
on conflict (id) do nothing;

drop policy if exists "documents_bucket_select_own" on storage.objects;
create policy "documents_bucket_select_own" on storage.objects
    for select to authenticated
    using (bucket_id = 'documents' and (storage.foldername(name))[1] = (select auth.uid())::text);

drop policy if exists "documents_bucket_insert_own" on storage.objects;
create policy "documents_bucket_insert_own" on storage.objects
    for insert to authenticated
    with check (bucket_id = 'documents' and (storage.foldername(name))[1] = (select auth.uid())::text);

drop policy if exists "documents_bucket_update_own" on storage.objects;
create policy "documents_bucket_update_own" on storage.objects
    for update to authenticated
    using (bucket_id = 'documents' and (storage.foldername(name))[1] = (select auth.uid())::text)
    with check (bucket_id = 'documents' and (storage.foldername(name))[1] = (select auth.uid())::text);

drop policy if exists "documents_bucket_delete_own" on storage.objects;
create policy "documents_bucket_delete_own" on storage.objects
    for delete to authenticated
    using (bucket_id = 'documents' and (storage.foldername(name))[1] = (select auth.uid())::text);

-- Realtime: the Documents page listens for status changes. RLS decides who gets which row.
do $$
begin
    if not exists (
        select 1 from pg_publication_tables
        where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'documents'
    ) then
        alter publication supabase_realtime add table public.documents;
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- 3. Vector search with a relevance threshold
-- ---------------------------------------------------------------------------
drop function if exists public.match_document_chunks(extensions.vector, int);

create or replace function public.match_document_chunks(
    query_embedding extensions.vector(1024),
    match_count int default 5,
    match_threshold float default 0
)
returns table (
    id uuid,
    document_id uuid,
    filename text,
    chunk_index int,
    content text,
    similarity float
)
language sql stable security invoker
set search_path = public, extensions
as $$
    select c.id, c.document_id, d.filename, c.chunk_index, c.content,
           1 - (c.embedding <=> query_embedding) as similarity
    from public.document_chunks c
    join public.documents d on d.id = c.document_id
    where d.status = 'completed'
      and 1 - (c.embedding <=> query_embedding) >= match_threshold
    order by c.embedding <=> query_embedding
    limit least(greatest(match_count, 1), 50);
$$;

revoke execute on function public.match_document_chunks(extensions.vector, int, float) from public, anon;
grant execute on function public.match_document_chunks(extensions.vector, int, float) to authenticated;
