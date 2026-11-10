-- Module 3: record manager. Content hashes let ingestion skip files it has
-- already processed and re-embed only the chunks that changed.

alter table public.documents add column if not exists content_hash text;
-- What the last ingestion did: {"embedded": n, "reused": n, "removed": n}.
alter table public.documents add column if not exists ingest_stats jsonb;
create index if not exists documents_user_hash_idx on public.documents (user_id, content_hash);

-- One document per filename per user: re-uploading a name updates that document.
-- Rename any pre-existing duplicates first ("notes.txt" -> "notes.txt (2)").
with ranked as (
    select id, row_number() over (partition by user_id, filename order by created_at, id) as rn
    from public.documents
)
update public.documents d
set filename = d.filename || ' (' || ranked.rn || ')'
from ranked
where ranked.id = d.id and ranked.rn > 1;

create unique index if not exists documents_user_filename_key
    on public.documents (user_id, filename);

alter table public.document_chunks add column if not exists content_hash text;

-- Kept chunks may move position when a document is updated.
drop policy if exists "document_chunks_update_own" on public.document_chunks;
create policy "document_chunks_update_own" on public.document_chunks
    for update to authenticated
    using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
