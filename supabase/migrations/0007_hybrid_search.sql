-- Module 6: hybrid search. A keyword leg (Postgres full-text search) and a
-- vector leg (pgvector) are fused with Reciprocal Rank Fusion (RRF):
--   score = 1 / (rrf_k + vector_rank) + 1 / (rrf_k + keyword_rank)

alter table public.document_chunks
    add column if not exists fts tsvector
    generated always as (to_tsvector('english', content)) stored;
create index if not exists document_chunks_fts_idx on public.document_chunks using gin (fts);

create or replace function public.hybrid_search_chunks(
    query_text text,
    query_embedding extensions.vector(1024),
    match_count int default 20,
    filter jsonb default '{}'::jsonb,
    filename_filter text default null,
    document_id_filter uuid default null,
    search_mode text default 'hybrid',  -- 'hybrid' | 'vector' | 'keyword'
    rrf_k int default 60
)
returns table (
    id uuid,
    document_id uuid,
    filename text,
    chunk_index int,
    content text,
    similarity float,
    vector_rank int,
    keyword_rank int,
    score float
)
language sql stable security invoker
set search_path = public, extensions
as $$
    with params as (
        select
            least(greatest(match_count, 1), 50) as k,
            -- websearch_to_tsquery ANDs every term, which is too strict for a
            -- natural-language question; OR the terms and let ranking sort it out.
            case
                when nullif(websearch_to_tsquery('english', query_text)::text, '') is null then null
                else to_tsquery(
                    'english',
                    replace(websearch_to_tsquery('english', query_text)::text, ' & ', ' | ')
                )
            end as tsq
    ),
    semantic as (
        select c.id,
               row_number() over (order by c.embedding <=> query_embedding) as rnk
        from public.document_chunks c
        join public.documents d on d.id = c.document_id
        where search_mode <> 'keyword'
          and d.status = 'completed'
          and d.metadata @> coalesce(filter, '{}'::jsonb)
          and (filename_filter is null or d.filename ilike '%' || filename_filter || '%')
          and (document_id_filter is null or d.id = document_id_filter)
        order by c.embedding <=> query_embedding
        limit (select k * 2 from params)
    ),
    keyword as (
        select c.id,
               row_number() over (order by ts_rank_cd(c.fts, p.tsq) desc, c.id) as rnk
        from public.document_chunks c
        join public.documents d on d.id = c.document_id
        cross join params p
        where search_mode <> 'vector'
          and p.tsq is not null
          and c.fts @@ p.tsq
          and d.status = 'completed'
          and d.metadata @> coalesce(filter, '{}'::jsonb)
          and (filename_filter is null or d.filename ilike '%' || filename_filter || '%')
          and (document_id_filter is null or d.id = document_id_filter)
        order by ts_rank_cd(c.fts, p.tsq) desc, c.id
        limit (select k * 2 from params)
    )
    select c.id, c.document_id, d.filename, c.chunk_index, c.content,
           1 - (c.embedding <=> query_embedding) as similarity,
           s.rnk::int as vector_rank,
           kw.rnk::int as keyword_rank,
           (coalesce(1.0 / (rrf_k + s.rnk), 0) + coalesce(1.0 / (rrf_k + kw.rnk), 0))::float as score
    from semantic s
    full outer join keyword kw on kw.id = s.id
    join public.document_chunks c on c.id = coalesce(s.id, kw.id)
    join public.documents d on d.id = c.document_id
    order by score desc, c.id
    limit (select k from params);
$$;

revoke execute on function
    public.hybrid_search_chunks(text, extensions.vector, int, jsonb, text, uuid, text, int)
    from public, anon;
grant execute on function
    public.hybrid_search_chunks(text, extensions.vector, int, jsonb, text, uuid, text, int)
    to authenticated;
