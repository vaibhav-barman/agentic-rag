import asyncio
import logging
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)

from app.config import get_settings
from app.db import Repo, get_repo
from app.schemas import Document, UploadResult
from app.services import record_manager
from app.services.ingestion import (
    ALLOWED_EXTENSIONS,
    extension_of,
    mime_type_of,
    process_document,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
async def upload_document(
    response: Response,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    repo: Repo = Depends(get_repo),
):
    """Store the file and return at once; ingestion continues in the background.

    The record manager decides first whether there is anything to do:
    `action` is created, updated, unchanged or duplicate.
    """
    settings = get_settings()
    filename = (file.filename or "").strip() or "upload"
    if extension_of(filename) not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type. Allowed: {allowed}",
        )
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File too large (max {mb} MB)",
        )
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty")

    content_hash = record_manager.sha256_hex(data)
    action, existing = record_manager.decide(repo, filename, content_hash)
    if existing is not None and action in {"unchanged", "duplicate"}:
        response.status_code = status.HTTP_200_OK
        return {**existing, "action": action}

    fields = {
        "file_size": len(data),
        "mime_type": mime_type_of(filename),
        "content_hash": content_hash,
    }
    if existing is not None:  # updated: same document id, new bytes
        response.status_code = status.HTTP_200_OK
        path = existing.get("storage_path") or _storage_path(repo, existing["id"], filename)
        document = repo.update_document(
            existing["id"], status="pending", error=None, storage_path=path, **fields
        )
    else:
        document_id = str(uuid.uuid4())
        path = _storage_path(repo, document_id, filename)
        document = repo.create_document(filename, id=document_id, storage_path=path, **fields)

    try:
        await asyncio.to_thread(repo.upload_file, path, data, fields["mime_type"])
    except Exception as exc:
        logger.exception("Storage upload failed for %s", filename)
        document = repo.update_document(
            document["id"], status="failed", error=f"Could not store file: {exc}"[:500]
        )
        return {**document, "action": action}

    background.add_task(process_document, repo, document)
    return {**document, "action": action}


def _storage_path(repo: Repo, document_id: str, filename: str) -> str:
    # The first folder must be the user's id: the Storage policies check it.
    return f"{repo.user_id}/{document_id}/original{extension_of(filename)}"


@router.get("", response_model=list[Document])
def list_documents(repo: Repo = Depends(get_repo)):
    return repo.list_documents()


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, repo: Repo = Depends(get_repo)):
    document = repo.get_document(document_id)
    # Chunks and stored text are removed by ON DELETE CASCADE.
    if document is None or not repo.delete_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    if document.get("storage_path"):
        try:
            repo.remove_file(document["storage_path"])
        except Exception:
            logger.exception("Could not remove stored file %s", document["storage_path"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)
