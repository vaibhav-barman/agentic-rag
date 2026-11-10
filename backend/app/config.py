from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """All configuration comes from env vars (or backend/.env). No admin UI."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str = ""
    # Legacy HS256 shared secret. Leave empty to verify via the project's JWKS
    # endpoint instead (asymmetric signing keys, the Supabase default for new projects).
    supabase_jwt_secret: str = ""
    supabase_jwt_audience: str = "authenticated"
    # Postgres connection string; only used by scripts/apply_migrations.py.
    supabase_db_url: str = ""
    storage_bucket: str = "documents"

    # Google Gemini API via its OpenAI-compatible endpoint (OpenAI SDK + base_url)
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_model: str = "gemini-flash-lite-latest"
    gemini_embedding_model: str = "gemini-embedding-001"
    # Must match document_chunks.embedding (vector(1024)) in migration 0003.
    embedding_dimensions: int = 1024

    # Chat
    chat_history_limit: int = 20
    max_tool_rounds: int = 6

    # Retrieval
    file_search_top_k: int = 5
    # "hybrid" (keyword + vector, fused with RRF), "vector" or "keyword".
    search_mode: str = "hybrid"
    # How many chunks the database returns before reranking cuts them to top_k.
    retrieval_candidates: int = 20
    # Vector-only search drops chunks below this cosine similarity.
    retrieval_min_similarity: float = 0.3
    rerank_enabled: bool = True
    # Reranked chunks scoring below this (0-1) are dropped.
    rerank_min_score: float = 0.2

    # Ingestion
    max_upload_bytes: int = 10 * 1024 * 1024
    chunk_size_chars: int = 3200
    chunk_overlap_chars: int = 400
    # "docling" (PDF/DOCX/HTML with layout and tables) or "basic" (pypdf/python-docx/bs4).
    document_parser: str = "docling"
    metadata_extraction_enabled: bool = True
    metadata_sample_chars: int = 8000

    # Tools
    # Web search is only offered to the model when this is set.
    tavily_api_key: str = ""
    web_search_max_results: int = 5
    sql_max_rows: int = 50

    # Sub-agent (whole-document analysis in an isolated context)
    subagent_max_chars: int = 400_000
    subagent_max_rounds: int = 4

    # LangSmith
    langsmith_api_key: str = ""
    langsmith_project: str = "agentic-rag"
    langsmith_tracing: bool = False

    # Comma-separated list of allowed browser origins.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def supabase_jwks_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def supabase_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"


@lru_cache
def get_settings() -> Settings:
    # Required fields are populated from the environment / .env by pydantic-settings.
    return Settings()  # pyright: ignore[reportCallIssue]
