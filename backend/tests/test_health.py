from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_vite_dev_origin():
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def _client_with_failing_repo(exc):
    from app.db import get_repo

    class BrokenRepo:
        user_id = "u"

        def list_documents(self):
            raise exc

    app.dependency_overrides[get_repo] = lambda: BrokenRepo()
    return TestClient(app, raise_server_exceptions=False)


def test_out_of_date_schema_is_a_readable_503_with_cors():
    """A missing column used to surface in the browser as a bare "Failed to fetch"."""
    from postgrest.exceptions import APIError

    exc = APIError({"code": "42703", "message": "column documents.metadata does not exist"})
    try:
        response = _client_with_failing_repo(exc).get(
            "/documents", headers={"Origin": "http://localhost:5173"}
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert "apply_migrations.py" in response.json()["detail"]
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_unexpected_errors_are_json_with_cors():
    try:
        response = _client_with_failing_repo(RuntimeError("boom")).get(
            "/documents", headers={"Origin": "http://localhost:5173"}
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 500 and "boom" in response.json()["detail"]
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
