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

    # OpenAI (Module 1)
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

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
    return Settings()
