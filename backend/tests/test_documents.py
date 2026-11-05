import uuid

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.config import get_settings
from app.db import get_repo
from app.main import app
from app.services import ingestion, llm
from tests.fakes import FakeRepo, FakeStore, fake_embed
from tests.test_threads_chat import h

settings = get_settings()
USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr(llm, "embed", fake_embed)

    def repo_override(user=Depends(get_current_user)):
        return FakeRepo(store, user.id)

    app.dependency_overrides[get_repo] = repo_override
    yield TestClient(app)
    app.dependency_overrides.clear()


# --- chunking -------------------------------------------------------------

def test_chunk_text_respects_size_and_overlap():
    words = " ".join(f"word{i}" for i in range(2000))
    chunks = ingestion.chunk_text(words, size=500, overlap=100)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)
    # Neighbours share text (overlap) and no word is cut in half.
    for a, b in zip(chunks, chunks[1:]):
        assert a.split()[-1] in b
        assert all(w.startswith("word") for w in b.split())
    # Everything is covered.
    assert chunks[-1].endswith("word1999")


def test_chunk_text_small_and_empty():
    assert ingestion.chunk_text("hello", size=500, overlap=100) == ["hello"]
    assert ingestion.chunk_text("   ", size=500, overlap=100) == []


def test_extract_text_pdf():
    from pypdf import PdfWriter

    import io
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    assert ingestion.extract_text("blank.pdf", buf.getvalue()).strip() == ""


# --- endpoints ------------------------------------------------------------

def upload(client, user, name, content, ctype="text/plain"):
    return client.post("/documents", headers=h(user), files={"file": (name, content, ctype)})


def test_upload_list_delete(client, store):
    r = upload(client, USER_A, "notes.md", b"# Notes\n\nThe sky is green here.")
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["status"] == "completed" and doc["chunk_count"] == 1
    assert len(store.chunks) == 1 and store.chunks[0]["embedding"] == [float(len(store.chunks[0]["content"])), 1.0]

    assert [d["id"] for d in client.get("/documents", headers=h(USER_A)).json()] == [doc["id"]]
    assert client.delete(f"/documents/{doc['id']}", headers=h(USER_A)).status_code == 204
    assert client.get("/documents", headers=h(USER_A)).json() == []
    assert store.chunks == []


def test_bad_type_is_415(client):
    r = upload(client, USER_A, "evil.exe", b"MZ")
    assert r.status_code == 415 and "Allowed" in r.json()["detail"]


def test_too_large_is_413(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 10)
    assert upload(client, USER_A, "big.txt", b"x" * 11).status_code == 413


def test_empty_file_is_400(client):
    assert upload(client, USER_A, "empty.txt", b"").status_code == 400


def test_non_utf8_text_marks_failed(client):
    r = upload(client, USER_A, "bin.txt", b"\xff\xfe\x00bad")
    assert r.status_code == 201
    assert r.json()["status"] == "failed" and "UTF-8" in r.json()["error"]


def test_embedding_failure_marks_failed(client, monkeypatch):
    async def boom(texts):
        raise RuntimeError("provider down")

    monkeypatch.setattr(llm, "embed", boom)
    r = upload(client, USER_A, "a.txt", b"hello")
    assert r.json()["status"] == "failed" and "provider down" in r.json()["error"]


def test_other_user_cannot_list_or_delete(client):
    doc = upload(client, USER_A, "a.txt", b"secret").json()
    assert client.get("/documents", headers=h(USER_B)).json() == []
    assert client.delete(f"/documents/{doc['id']}", headers=h(USER_B)).status_code == 404
    assert len(client.get("/documents", headers=h(USER_A)).json()) == 1


def test_documents_require_auth(client):
    assert client.get("/documents").status_code == 401
