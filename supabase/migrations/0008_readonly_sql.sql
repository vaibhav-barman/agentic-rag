-- Module 7: text-to-SQL. The model writes a SELECT; this function runs it as the
-- calling user (SECURITY INVOKER), so Row-Level Security limits it to their rows.
-- Defence in depth: single read-only statement, public schema only, 5s timeout,
-- at most 100 rows.

create or replace function public.execute_readonly_sql(query text)
returns jsonb
language plpgsql security invoker
set search_path = public, extensions
as $$
declare
    q text := regexp_replace(btrim(coalesce(query, '')), ';\s*$', '');
    lowered text := lower(q);
    result jsonb;
begin
    if q = '' then
        raise exception 'Query is empty';
    end if;
    if position(';' in q) > 0 then
        raise exception 'Only a single statement is allowed';
    end if;
    if lowered !~ '^(select|with)\M' then
        raise exception 'Only SELECT queries are allowed';
    end if;
    if lowered ~ '\m(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call|do|set|reset|execute|vacuum|listen|notify|lock|refresh|into|set_config|dblink|nextval|setval)\M' then
        raise exception 'Only read-only SELECT queries are allowed';
    end if;
    if lowered ~ '\m(auth|storage|vault|extensions|realtime|net|cron|graphql|graphql_public|pgsodium|supabase_functions|information_schema)\s*\.'
       or lowered ~ '\mpg_[a-z0-9_]+' then
        raise exception 'Only tables in the public schema can be queried';
    end if;

    set local statement_timeout = '5s';
    set local transaction_read_only = on;
    execute format(
        'select coalesce(jsonb_agg(to_jsonb(t)), ''[]''::jsonb) from (select * from (%s) q limit 100) t',
        q
    ) into result;
    return result;
end;
$$;

revoke execute on function public.execute_readonly_sql(text) from public, anon;
grant execute on function public.execute_readonly_sql(text) to authenticated;
