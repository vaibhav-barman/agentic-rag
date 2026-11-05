from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from app.config import get_settings
from app.db import Repo, get_repo
from app.schemas import Document
from app.services.ingestion import ALLOWED_EXTENSIONS, extension_of, ingest

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=Document, status_code=status.HTTP_201_CREATED)
async def upload_document(file: UploadFile = File(...), repo: Repo = Depends(get_repo)):
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

    document = repo.create_document(filename)
    return await ingest(repo, document["id"], filename, data)


@router.get("", response_model=list[Document])
def list_documents(repo: Repo = Depends(get_repo)):
    return repo.list_documents()


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, repo: Repo = Depends(get_repo)):
    # Chunks are removed by ON DELETE CASCADE.
    if not repo.delete_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
