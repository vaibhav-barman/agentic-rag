-- Module 4: LLM-extracted document metadata, and retrieval filtered by it.

alter table public.documents add column if not exists metadata jsonb not null default '{}'::jsonb;
create index if not exists documents_metadata_idx on public.documents using gin (metadata jsonb_path_ops);

drop function if exists public.match_document_chunks(extensions.vector, int, float);

-- `filter` is matched with jsonb containment, e.g.
--   {"document_type": "report"}  or  {"topics": ["pricing"]}
create or replace function public.match_document_chunks(
    query_embedding extensions.vector(1024),
    match_count int default 5,
    match_threshold float default 0,
    filter jsonb default '{}'::jsonb,
    filename_filter text default null,
    document_id_filter uuid default null
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
      and d.metadata @> coalesce(filter, '{}'::jsonb)
      and (filename_filter is null or d.filename ilike '%' || filename_filter || '%')
      and (document_id_filter is null or d.id = document_id_filter)
      and 1 - (c.embedding <=> query_embedding) >= match_threshold
    order by c.embedding <=> query_embedding
    limit least(greatest(match_count, 1), 50);
$$;

revoke execute on function
    public.match_document_chunks(extensions.vector, int, float, jsonb, text, uuid) from public, anon;
grant execute on function
    public.match_document_chunks(extensions.vector, int, float, jsonb, text, uuid) to authenticated;
