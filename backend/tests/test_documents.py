import uuid

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.config import get_settings
from app.db import get_repo
from app.main import app
from app.services import ingestion, llm
from tests.fakes import FakeRepo, FakeStore, ScriptedStructured, fake_embed, no_structured
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
    monkeypatch.setattr(llm, "complete_structured", no_structured)
    monkeypatch.setattr(settings, "document_parser", "basic")

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
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert a.split()[-1] in b
        assert all(w.startswith("word") for w in b.split())
    # Everything is covered.
    assert chunks[-1].endswith("word1999")


def test_chunk_text_small_and_empty():
    assert ingestion.chunk_text("hello", size=500, overlap=100) == ["hello"]
    assert ingestion.chunk_text("   ", size=500, overlap=100) == []


def test_chunk_text_prefers_heading_boundaries():
    text = "# One\n\n" + "alpha " * 60 + "\n\n# Two\n\n" + "beta " * 60
    chunks = ingestion.chunk_text(text, size=500, overlap=50)
    assert chunks[0].endswith("alpha")
    assert any(c.startswith("# Two") or "\n# Two" in c[:60] for c in chunks[1:])


# --- Module 5: parsing ------------------------------------------------------


def _pdf(text: str | None = None) -> bytes:
    import io

    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _docx() -> bytes:
    import io

    import docx

    d = docx.Document()
    d.add_heading("Launch plan", 1)
    d.add_paragraph("The codename is HERON.")
    table = d.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Owner", "Date"
    table.cell(1, 0).text, table.cell(1, 1).text = "Marisol", "March"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


HTML = (
    b"<html><head><style>p{color:red}</style><script>var hidden = 1</script></head>"
    b"<body><h1>Pricing</h1><p>The plan costs <b>42 dollars</b>.</p></body></html>"
)


@pytest.mark.parametrize("parser", ["basic", "docling"])
def test_parse_docx_and_html(parser, monkeypatch):
    if parser == "docling":
        pytest.importorskip("docling")
    monkeypatch.setattr(settings, "document_parser", parser)
    docx_md = ingestion.parse_document("plan.docx", _docx())
    assert "# Launch plan" in docx_md and "HERON" in docx_md and "Marisol" in docx_md
    html_md = ingestion.parse_document("pricing.html", HTML)
    assert "# Pricing" in html_md and "42 dollars" in html_md
    assert "hidden" not in html_md and "color:red" not in html_md


def test_parse_text_markdown_and_pdf(monkeypatch):
    monkeypatch.setattr(settings, "document_parser", "basic")
    assert ingestion.parse_document("a.md", b"# Hi\n\ntext") == "# Hi\n\ntext"
    assert ingestion.parse_document("blank.pdf", _pdf()).strip() == ""
    with pytest.raises(ingestion.IngestionError, match="UTF-8"):
        ingestion.parse_document("a.txt", b"\xff\xfe\x00bad")
    with pytest.raises(ingestion.IngestionError, match="Unsupported"):
        ingestion.parse_document("a.exe", b"MZ")


@pytest.mark.parametrize("parser", ["basic", "docling"])
def test_corrupt_docx_gives_readable_error(parser, monkeypatch):
    if parser == "docling":
        pytest.importorskip("docling")
    monkeypatch.setattr(settings, "document_parser", parser)
    with pytest.raises(ingestion.IngestionError, match="Could not read DOCX"):
        ingestion.parse_document("broken.docx", b"this is not a zip file")


# --- Module 3: record manager (pure logic) ------------------------------------


def test_plan_chunks_reuses_moves_and_deletes():
    from app.services.record_manager import plan_chunks

    existing = [
        {"id": "a", "chunk_index": 0, "content_hash": "h-a"},
        {"id": "b", "chunk_index": 1, "content_hash": "h-b"},
        {"id": "c", "chunk_index": 2, "content_hash": "h-c"},
        {"id": "old", "chunk_index": 3, "content_hash": None},  # ingested before hashing
    ]
    plan = plan_chunks(existing, ["h-a", "h-new", "h-c", "h-c"])
    assert plan.to_embed == [1, 3]  # the new chunk, and the second copy of h-c
    assert plan.to_move == []
    assert sorted(plan.to_delete) == ["b", "old"]
    assert plan.stats == {"embedded": 2, "reused": 2, "removed": 2}

    shifted = plan_chunks(existing[:3], ["h-new", "h-a", "h-b", "h-c"])
    assert shifted.to_embed == [0]
    assert shifted.to_move == [("a", 1), ("b", 2), ("c", 3)]
    assert shifted.to_delete == []


# --- endpoints ------------------------------------------------------------


def upload(client, user, name, content, ctype="text/plain"):
    return client.post("/documents", headers=h(user), files={"file": (name, content, ctype)})


def docs(client, user):
    return client.get("/documents", headers=h(user)).json()


def test_upload_is_async_then_completes(client, store):
    """Module 2: the response says `pending`; the background task finishes the job."""
    r = upload(client, USER_A, "notes.md", b"# Notes\n\nThe sky is green here.")
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["status"] == "pending" and created["action"] == "created"

    # The file went to Storage under the user's own folder.
    [(path, stored)] = store.files.items()
    assert path == f"{USER_A}/{created['id']}/original.md" and stored.startswith(b"# Notes")

    # TestClient runs background tasks before returning, so ingestion is done.
    [doc] = docs(client, USER_A)
    assert doc["status"] == "completed" and doc["chunk_count"] == 1
    assert doc["file_size"] == len(stored)
    assert doc["ingest_stats"] == {"embedded": 1, "reused": 0, "removed": 0}
    [chunk] = store.chunks
    assert chunk["embedding"] == [float(len(chunk["content"])), 1.0]
    assert chunk["content_hash"] and store.contents[doc["id"]].startswith("# Notes")


def test_delete_removes_chunks_content_and_stored_file(client, store):
    doc = upload(client, USER_A, "notes.md", b"hello world").json()
    assert store.files and store.chunks and store.contents
    assert client.delete(f"/documents/{doc['id']}", headers=h(USER_A)).status_code == 204
    assert docs(client, USER_A) == []
    assert store.chunks == [] and store.files == {} and store.contents == {}


def test_bad_type_is_415(client):
    r = upload(client, USER_A, "evil.exe", b"MZ")
    assert r.status_code == 415 and "Allowed" in r.json()["detail"]


def test_too_large_is_413(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 10)
    assert upload(client, USER_A, "big.txt", b"x" * 11).status_code == 413


def test_empty_file_is_400(client):
    assert upload(client, USER_A, "empty.txt", b"").status_code == 400


def test_non_utf8_text_marks_failed(client):
    assert upload(client, USER_A, "bin.txt", b"\xff\xfe\x00bad").status_code == 201
    [doc] = docs(client, USER_A)
    assert doc["status"] == "failed" and "UTF-8" in doc["error"]


def test_embedding_failure_marks_failed(client, monkeypatch):
    async def boom(texts):
        raise RuntimeError("provider down")

    monkeypatch.setattr(llm, "embed", boom)
    upload(client, USER_A, "a.txt", b"hello")
    [doc] = docs(client, USER_A)
    assert doc["status"] == "failed" and "provider down" in doc["error"]


def test_storage_failure_marks_failed(client, monkeypatch):
    def boom(self, path, data, mime_type):
        raise RuntimeError("bucket missing")

    monkeypatch.setattr(FakeRepo, "upload_file", boom)
    r = upload(client, USER_A, "a.txt", b"hello")
    assert r.json()["status"] == "failed" and "bucket missing" in r.json()["error"]


def test_docx_and_html_uploads_complete(client, store):
    upload(client, USER_A, "plan.docx", _docx(), "application/octet-stream")
    upload(client, USER_A, "pricing.html", HTML, "text/html")
    assert {d["filename"]: d["status"] for d in docs(client, USER_A)} == {
        "plan.docx": "completed",
        "pricing.html": "completed",
    }
    assert any("HERON" in c["content"] for c in store.chunks)


def test_other_user_cannot_list_or_delete(client):
    doc = upload(client, USER_A, "a.txt", b"secret").json()
    assert docs(client, USER_B) == []
    assert client.delete(f"/documents/{doc['id']}", headers=h(USER_B)).status_code == 404
    assert len(docs(client, USER_A)) == 1


def test_documents_require_auth(client):
    assert client.get("/documents").status_code == 401


# --- Module 3: record manager (through the API) ---------------------------------


@pytest.fixture
def embed_calls(monkeypatch):
    calls: list[list[str]] = []

    async def counting_embed(texts):
        calls.append(list(texts))
        return await fake_embed(texts)

    monkeypatch.setattr(llm, "embed", counting_embed)
    return calls


def test_same_file_twice_is_processed_once(client, store, embed_calls):
    first = upload(client, USER_A, "a.txt", b"hello world")
    again = upload(client, USER_A, "a.txt", b"hello world")
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["action"] == "unchanged" and again.json()["id"] == first.json()["id"]
    assert len(docs(client, USER_A)) == 1 and len(embed_calls) == 1 and len(store.chunks) == 1


def test_same_bytes_under_another_name_is_a_duplicate(client, embed_calls):
    first = upload(client, USER_A, "a.txt", b"hello world").json()
    dup = upload(client, USER_A, "copy-of-a.txt", b"hello world")
    assert dup.status_code == 200 and dup.json()["action"] == "duplicate"
    assert dup.json()["id"] == first["id"] and dup.json()["filename"] == "a.txt"
    assert len(docs(client, USER_A)) == 1 and len(embed_calls) == 1
    # Another user uploading the same bytes gets their own document.
    assert upload(client, USER_B, "a.txt", b"hello world").json()["action"] == "created"


def test_changed_file_only_embeds_changed_chunks(client, store, embed_calls, monkeypatch):
    monkeypatch.setattr(settings, "chunk_size_chars", 300)
    monkeypatch.setattr(settings, "chunk_overlap_chars", 0)
    paragraphs = [f"Paragraph {i}. " + (f"word{i} " * 30).strip() for i in range(6)]
    v1 = "\n\n".join(paragraphs).encode()
    doc = upload(client, USER_A, "big.md", v1).json()
    total = len(store.chunks)
    assert total >= 6 and sum(len(c) for c in embed_calls) == total

    # Append a paragraph: every existing chunk is reused, one new chunk is embedded.
    new_paragraph = "Paragraph 6. " + ("zebra " * 30).strip()
    v2 = v1 + b"\n\n" + new_paragraph.encode()
    updated = upload(client, USER_A, "big.md", v2)
    assert updated.status_code == 200 and updated.json()["action"] == "updated"
    assert updated.json()["id"] == doc["id"]
    [row] = docs(client, USER_A)
    assert row["ingest_stats"] == {"embedded": 1, "reused": total, "removed": 0}
    assert row["chunk_count"] == total + 1 == len(store.chunks)
    assert embed_calls[-1] == [new_paragraph]

    # Rewrite the first paragraph: its chunk(s) are replaced, the rest are kept.
    v3 = v2.replace(b"Paragraph 0.", b"Opening section, rewritten.")
    upload(client, USER_A, "big.md", v3)
    [row] = docs(client, USER_A)
    stats = row["ingest_stats"]
    assert stats["embedded"] >= 1 and stats["embedded"] == stats["removed"]
    assert stats["reused"] >= total - 1
    indexes = sorted(c["chunk_index"] for c in store.chunks)
    assert indexes == list(range(row["chunk_count"]))
    assert not any("Paragraph 0." in c["content"] for c in store.chunks)


def test_failed_upload_can_be_retried_with_the_same_file(client, monkeypatch):
    async def boom(texts):
        raise RuntimeError("provider down")

    monkeypatch.setattr(llm, "embed", boom)
    upload(client, USER_A, "a.txt", b"hello")
    monkeypatch.setattr(llm, "embed", fake_embed)
    retry = upload(client, USER_A, "a.txt", b"hello")
    assert retry.json()["action"] == "updated"
    assert [d["status"] for d in docs(client, USER_A)] == ["completed"]


# --- Module 4: metadata extraction ----------------------------------------------


def test_metadata_is_extracted_and_stored(client, monkeypatch):
    scripted = ScriptedStructured(
        {
            "title": "Q3 Sales",
            "summary": "Revenue grew.",
            "document_type": "report",
            "topics": ["Pricing", " pricing ", "EMEA"],
            "key_entities": ["Acme"],
        }
    )
    monkeypatch.setattr(llm, "complete_structured", scripted.complete_structured)
    upload(client, USER_A, "q3.md", b"# Q3 Sales\n\nRevenue grew 12%.")
    [doc] = docs(client, USER_A)
    assert doc["status"] == "completed"
    assert doc["metadata"]["document_type"] == "report"
    assert doc["metadata"]["topics"] == ["pricing", "emea"]  # lowercased, deduplicated
    sent = scripted.calls[0]["messages"][-1]["content"]
    assert "q3.md" in sent and "Revenue grew 12%" in sent


def test_metadata_failure_does_not_fail_ingestion(client, monkeypatch):
    scripted = ScriptedStructured({"title": "x", "summary": "y", "document_type": "not-a-type"})
    monkeypatch.setattr(llm, "complete_structured", scripted.complete_structured)
    upload(client, USER_A, "a.txt", b"hello")
    [doc] = docs(client, USER_A)
    assert doc["status"] == "completed" and doc["metadata"] == {}
