import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from app.db import Repo, get_repo
from app.schemas import ChatRequest, Message, Thread, ThreadCreate
from app.services.chat import run_chat_turn

router = APIRouter(prefix="/threads", tags=["threads"])


def _thread_or_404(repo: Repo, thread_id: str) -> dict:
    thread = repo.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@router.post("", response_model=Thread, status_code=status.HTTP_201_CREATED)
def create_thread(body: ThreadCreate | None = None, repo: Repo = Depends(get_repo)):
    return repo.create_thread(title=body.title if body else None)


@router.get("", response_model=list[Thread])
def list_threads(repo: Repo = Depends(get_repo)):
    return repo.list_threads()


@router.get("/{thread_id}/messages", response_model=list[Message])
def list_messages(thread_id: str, repo: Repo = Depends(get_repo)):
    _thread_or_404(repo, thread_id)
    return repo.list_messages(thread_id)


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_thread(thread_id: str, repo: Repo = Depends(get_repo)):
    if not repo.delete_thread(thread_id):
        raise HTTPException(status_code=404, detail="Thread not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/{thread_id}/chat")
def chat(thread_id: str, body: ChatRequest, repo: Repo = Depends(get_repo)):
    thread = _thread_or_404(repo, thread_id)
    user_message = repo.add_message(thread_id, "user", body.content)

    async def event_stream():
        yield sse("user_message", {"id": user_message["id"]})
        async for event, data in run_chat_turn(repo, thread, body.content):
            yield sse(event, data)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
