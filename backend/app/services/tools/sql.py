"""query_database: text-to-SQL over the user's own structured data.

The model writes one SELECT. It is checked here, then run by the
execute_readonly_sql Postgres function as the user, so Row-Level Security
limits it to their rows whatever the SQL says.
"""

import json
import re

from app.config import get_settings
from app.services.tools.base import Tool, ToolContext, ToolOutput, function_schema

DB_SCHEMA = """\
PostgreSQL tables (rows are already limited to the current user):

documents(id uuid, filename text, status text, chunk_count int, file_size bigint  -- bytes,
          mime_type text, metadata jsonb, created_at timestamptz, updated_at timestamptz)
  metadata keys: title, summary, document_type, topics (array of text), language,
                 key_entities (array of text), document_date ('YYYY-MM-DD')
  e.g. metadata->>'document_type' = 'report'   |   metadata->'topics' ? 'pricing'
document_chunks(id uuid, document_id uuid -> documents.id, chunk_index int, content text,
                created_at timestamptz)
threads(id uuid, title text, created_at timestamptz, updated_at timestamptz)
messages(id uuid, thread_id uuid -> threads.id, role text  -- 'user' | 'assistant',
         content text, created_at timestamptz)"""

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call|do|set|reset|"
    r"execute|vacuum|listen|notify|lock|refresh|into|set_config|dblink|nextval|setval)\b",
    re.IGNORECASE,
)
OTHER_SCHEMAS = re.compile(
    r"\b(auth|storage|vault|extensions|realtime|net|cron|graphql|graphql_public|pgsodium|"
    r"supabase_functions|information_schema)\s*\.|\bpg_[a-z0-9_]+",
    re.IGNORECASE,
)
HIDDEN_COLUMNS = {"embedding", "fts"}
MAX_CELL_CHARS = 300
MAX_RESULT_CHARS = 8000


def validate_sql(sql: str) -> str:
    """Return the cleaned statement or raise ValueError saying why it is refused."""
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise ValueError("Query is empty")
    if ";" in statement:
        raise ValueError("Only a single statement is allowed")
    if not re.match(r"(select|with)\b", statement, re.IGNORECASE):
        raise ValueError("Only SELECT queries are allowed")
    if FORBIDDEN.search(statement):
        raise ValueError("Only read-only SELECT queries are allowed")
    if OTHER_SCHEMAS.search(statement):
        raise ValueError("Only tables in the public schema can be queried")
    return statement


def _clean_rows(rows: list[dict]) -> list[dict]:
    cleaned = []
    for row in rows:
        out = {}
        for key, value in row.items():
            if key in HIDDEN_COLUMNS:
                continue
            if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
                value = value[:MAX_CELL_CHARS] + "…"
            out[key] = value
        cleaned.append(out)
    return cleaned


class QueryDatabaseTool(Tool):
    name = "query_database"
    guidance = (
        "Use query_database for questions about the library as data: counts, lists, "
        "dates, sizes, document types or topics, or the chat history (for example "
        "'how many reports did I upload this month?'). Use file_search, not SQL, for "
        "what a document says."
    )

    def available(self, ctx: ToolContext) -> bool:
        return bool(ctx.library)

    def schema(self, ctx: ToolContext) -> dict:
        return function_schema(
            self.name,
            "Run one read-only PostgreSQL SELECT over the user's data and get the rows "
            "back as JSON (at most 100).\n\n" + DB_SCHEMA,
            {
                "sql": {
                    "type": "string",
                    "description": "A single SELECT statement. No semicolons, no writes.",
                }
            },
            ["sql"],
        )

    async def run(self, ctx: ToolContext, step_id: str, args: dict):
        sql = str(args.get("sql") or "")
        try:
            statement = validate_sql(sql)
        except ValueError as exc:
            yield ToolOutput(
                content=f"Query refused: {exc}", summary=str(exc), ok=False, data={"sql": sql}
            )
            return
        try:
            rows = ctx.repo.run_sql(statement)
        except Exception as exc:
            # Postgres' message helps the model fix the query on its next try.
            message = getattr(exc, "message", None) or str(exc)
            yield ToolOutput(
                content=f"Query failed: {message}",
                summary=f"Query failed: {message}"[:200],
                ok=False,
                data={"sql": statement},
            )
            return

        rows = _clean_rows(rows or [])
        shown = rows[: get_settings().sql_max_rows]
        content = json.dumps(shown, default=str)
        if len(content) > MAX_RESULT_CHARS:
            content = content[:MAX_RESULT_CHARS] + "… (truncated)"
        if len(rows) > len(shown):
            content += f"\n({len(rows)} rows in total; showing the first {len(shown)})"
        yield ToolOutput(
            content=content,
            summary=f"{len(rows)} row{'s' if len(rows) != 1 else ''}",
            data={
                "sql": statement,
                "columns": list(shown[0].keys()) if shown else [],
                "rows": shown[:20],
                "row_count": len(rows),
            },
        )
