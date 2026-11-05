"""Supabase JWT verification.

Supports both Supabase signing modes:
- Legacy shared secret (HS256): set SUPABASE_JWT_SECRET.
- Asymmetric signing keys (ES256/RS256, default for new projects): leave the
  secret empty; keys are fetched from the project's JWKS endpoint.
"""

from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.schemas import CurrentUser

ASYMMETRIC_ALGORITHMS = {"ES256", "RS256", "EdDSA"}

_bearer = HTTPBearer(auto_error=False)


@lru_cache
def _get_jwk_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(get_settings().supabase_jwks_url, cache_keys=True)


def _unauthorized(detail: str = "Invalid or missing access token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify_token(token: str) -> dict:
    """Return the verified claims of a Supabase access token or raise 401."""
    settings = get_settings()
    try:
        alg = jwt.get_unverified_header(token).get("alg")
        if alg == "HS256":
            # Only accept symmetric tokens when a shared secret is configured;
            # otherwise an attacker could pick the algorithm.
            if not settings.supabase_jwt_secret:
                raise _unauthorized()
            key = settings.supabase_jwt_secret
        elif alg in ASYMMETRIC_ALGORITHMS:
            key = _get_jwk_client().get_signing_key_from_jwt(token).key
        else:
            raise _unauthorized()

        return jwt.decode(
            token,
            key,
            algorithms=[alg],
            audience=settings.supabase_jwt_audience,
            options={"require": ["sub", "exp"]},
        )
    except HTTPException:
        raise
    except (jwt.PyJWTError, ValueError) as exc:
        raise _unauthorized() from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    claims = verify_token(credentials.credentials)
    return CurrentUser(
        id=claims["sub"],
        email=claims.get("email"),
        access_token=credentials.credentials,
    )
