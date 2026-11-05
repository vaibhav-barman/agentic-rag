import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app import auth
from app.config import get_settings
from app.main import app

client = TestClient(app)
settings = get_settings()


def make_token(
    *,
    secret: str | None = None,
    sub: str | None = None,
    email: str = "alice@example.com",
    aud: str = "authenticated",
    exp_offset: int = 3600,
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub or str(uuid.uuid4()),
        "email": email,
        "aud": aud,
        "role": "authenticated",
        "iss": settings.supabase_issuer,
        "iat": now,
        "exp": now + exp_offset,
    }
    return jwt.encode(payload, secret or settings.supabase_jwt_secret, algorithm="HS256")


def test_me_without_token_is_401():
    assert client.get("/me").status_code == 401


def test_me_with_non_bearer_scheme_is_401():
    response = client.get("/me", headers={"Authorization": f"Basic {make_token()}"})
    assert response.status_code == 401


def test_me_with_garbage_token_is_401():
    response = client.get("/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_me_with_wrong_signature_is_401():
    token = make_token(secret="a-different-secret-that-is-at-least-32-bytes")
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_me_with_expired_token_is_401():
    token = make_token(exp_offset=-60)
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_me_with_wrong_audience_is_401():
    token = make_token(aud="anon")
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_me_with_valid_token_returns_id_and_email():
    user_id = str(uuid.uuid4())
    token = make_token(sub=user_id, email="alice@example.com")
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"id": user_id, "email": "alice@example.com"}


def test_me_with_asymmetric_jwks_token(monkeypatch):
    """Projects on asymmetric signing keys: verify ES256 tokens via JWKS."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    class FakeSigningKey:
        key = public_key

    class FakeJWKClient:
        def get_signing_key_from_jwt(self, token):
            return FakeSigningKey()

    monkeypatch.setattr(auth, "_get_jwk_client", lambda: FakeJWKClient())

    user_id = str(uuid.uuid4())
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": user_id,
            "email": "bob@example.com",
            "aud": "authenticated",
            "iss": settings.supabase_issuer,
            "iat": now,
            "exp": now + 3600,
        },
        private_key,
        algorithm="ES256",
        headers={"kid": "test-kid"},
    )
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"id": user_id, "email": "bob@example.com"}


def test_hs256_token_rejected_when_no_secret_configured(monkeypatch):
    """With no shared secret, an HS256 token must not be accepted (no alg confusion)."""
    monkeypatch.setattr(settings, "supabase_jwt_secret", "")
    token = make_token(secret="test-jwt-secret-that-is-at-least-32-bytes-long")
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.parametrize("missing", ["sub"])
def test_me_with_missing_sub_is_401(missing):
    now = int(time.time())
    token = jwt.encode(
        {"email": "x@example.com", "aud": "authenticated", "iat": now, "exp": now + 3600},
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
