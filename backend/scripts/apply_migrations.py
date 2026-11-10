"""Apply SQL migrations from supabase/migrations to the hosted database.

Needs SUPABASE_DB_URL in backend/.env (Supabase -> Connect -> Session pooler URI).

    venv/bin/python scripts/apply_migrations.py            # apply everything not yet recorded
    venv/bin/python scripts/apply_migrations.py --status   # list applied / pending
    venv/bin/python scripts/apply_migrations.py --baseline 0003   # record 0001-0003 as applied

Each file runs in its own transaction and is recorded in public.schema_migrations.
Migrations 0001-0003 were applied by hand before this script existed, so the first
run records them as a baseline instead of re-running them.
"""

import sys
from pathlib import Path

import psycopg
from dotenv import dotenv_values

BACKEND = Path(__file__).resolve().parent.parent
MIGRATIONS = BACKEND.parent / "supabase" / "migrations"
BASELINE = "0003"


def main() -> int:
    url = dotenv_values(BACKEND / ".env").get("SUPABASE_DB_URL")
    if not url:
        print("SUPABASE_DB_URL is not set in backend/.env", file=sys.stderr)
        return 2
    args = sys.argv[1:]
    files = sorted(MIGRATIONS.glob("*.sql"))

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            """
            create table if not exists public.schema_migrations (
                name text primary key,
                applied_at timestamptz not null default now()
            );
            alter table public.schema_migrations enable row level security;
            """
        )
        applied = {r[0] for r in conn.execute("select name from public.schema_migrations")}

        baseline = args[1] if args[:1] == ["--baseline"] and len(args) > 1 else None
        if baseline is None and not applied:
            baseline = BASELINE
        if baseline:
            for f in files:
                if f.name[:4] <= baseline and f.name not in applied:
                    conn.execute(
                        "insert into public.schema_migrations (name) values (%s)", (f.name,)
                    )
                    applied.add(f.name)
                    print(f"baseline  {f.name}")
            if args[:1] == ["--baseline"]:
                return 0

        pending = [f for f in files if f.name not in applied]
        if args[:1] == ["--status"]:
            for f in files:
                print(("applied   " if f.name in applied else "pending   ") + f.name)
            return 0

        for f in pending:
            with conn.transaction():
                conn.execute(f.read_text())  # pyright: ignore[reportArgumentType]
                conn.execute("insert into public.schema_migrations (name) values (%s)", (f.name,))
            print(f"applied   {f.name}")
        if not pending:
            print("Nothing to apply.")
        # Make PostgREST pick up new columns and functions straight away.
        conn.execute("notify pgrst, 'reload schema'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
