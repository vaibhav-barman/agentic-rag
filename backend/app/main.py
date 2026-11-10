import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError

from app.config import get_settings
from app.routers import documents, me, threads
from app.services.llm import configure_langsmith_env

logger = logging.getLogger(__name__)
settings = get_settings()
configure_langsmith_env()

app = FastAPI(title="Glossa API")

# Postgres / PostgREST codes that mean "the schema is older than the code":
# undefined column, undefined table, and PostgREST's "not in the schema cache".
SCHEMA_OUT_OF_DATE = {"42703", "42P01", "42883", "PGRST202", "PGRST204", "PGRST205"}
MIGRATIONS_HINT = (
    "The database is missing migrations. Run "
    "`backend/venv/bin/python backend/scripts/apply_migrations.py` "
    "(or paste the files in supabase/migrations into the Supabase SQL Editor), then retry."
)


@app.middleware("http")
async def errors_as_json(request: Request, call_next):
    """Turn unhandled errors into JSON responses.

    Registered before CORSMiddleware so the CORS headers are still added: without
    them the browser hides the response and the UI can only say "Failed to fetch".
    """
    try:
        return await call_next(request)
    except APIError as exc:
        logger.exception("Database error on %s %s", request.method, request.url.path)
        if exc.code in SCHEMA_OUT_OF_DATE:
            return JSONResponse(status_code=503, content={"detail": MIGRATIONS_HINT})
        return JSONResponse(
            status_code=502, content={"detail": f"Database error: {exc.message or exc.code}"}
        )
    except Exception as exc:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500, content={"detail": f"Server error: {type(exc).__name__}: {exc}"[:300]}
        )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(me.router)
app.include_router(threads.router)
app.include_router(documents.router)
