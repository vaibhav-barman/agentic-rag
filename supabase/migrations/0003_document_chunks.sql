-- File search: chunks + embeddings in pgvector, searched as the calling user (RLS).
-- Dimension 1024 must match EMBEDDING_DIMENSIONS in backend config.

create extension if not exists vector with schema extensions;

create table if not exists public.document_chunks (
    id          uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.documents (id) on delete cascade,
    user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
    chunk_index int not null,
    content     text not null,
    embedding   extensions.vector(1024) not null,
    created_at  timestamptz not null default now()
);
create index if not exists document_chunks_document_idx on public.document_chunks (document_id);
create index if not exists document_chunks_embedding_idx
    on public.document_chunks using hnsw (embedding extensions.vector_cosine_ops);

alter table public.document_chunks enable row level security;

create policy "document_chunks_select_own" on public.document_chunks
    for select to authenticated using ((select auth.uid()) = user_id);
create policy "document_chunks_insert_own" on public.document_chunks
    for insert to authenticated with check (
        (select auth.uid()) = user_id
        and exists (
            select 1 from public.documents d
            where d.id = document_id and d.user_id = (select auth.uid())
        )
    );
create policy "document_chunks_delete_own" on public.document_chunks
    for delete to authenticated using ((select auth.uid()) = user_id);

-- Top-k chunks from the caller's completed documents. SECURITY INVOKER so RLS applies.
create or replace function public.match_document_chunks(
    query_embedding extensions.vector(1024),
    match_count int default 5
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
    order by c.embedding <=> query_embedding
    limit least(greatest(match_count, 1), 20);
$$;

grant execute on function public.match_document_chunks(extensions.vector, int) to authenticated;
