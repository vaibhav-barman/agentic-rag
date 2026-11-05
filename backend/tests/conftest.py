import os
import sys
from pathlib import Path

# Make `app` importable when running `pytest` from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Deterministic settings for unit tests; never hit real services.
os.environ.setdefault("SUPABASE_URL", "https://test-project.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret-that-is-at-least-32-bytes-long")
os.environ.setdefault("LANGSMITH_TRACING", "false")
