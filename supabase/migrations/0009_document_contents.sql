-- Module 8: the full parsed text of each document, for the sub-agent that reads
-- whole documents. Kept out of `documents` so list queries and Realtime payloads stay small.

create table if not exists public.document_contents (
    document_id uuid primary key references public.documents (id) on delete cascade,
    user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
    content     text not null,
    updated_at  timestamptz not null default now()
);

alter table public.document_contents enable row level security;

drop policy if exists "document_contents_select_own" on public.document_contents;
create policy "document_contents_select_own" on public.document_contents
    for select to authenticated using ((select auth.uid()) = user_id);

drop policy if exists "document_contents_insert_own" on public.document_contents;
create policy "document_contents_insert_own" on public.document_contents
    for insert to authenticated with check (
        (select auth.uid()) = user_id
        and exists (
            select 1 from public.documents d
            where d.id = document_id and d.user_id = (select auth.uid())
        )
    );

drop policy if exists "document_contents_update_own" on public.document_contents;
create policy "document_contents_update_own" on public.document_contents
    for update to authenticated
    using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

drop policy if exists "document_contents_delete_own" on public.document_contents;
create policy "document_contents_delete_own" on public.document_contents
    for delete to authenticated using ((select auth.uid()) = user_id);
