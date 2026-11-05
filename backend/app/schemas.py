from pydantic import BaseModel, Field


class CurrentUser(BaseModel):
    """The authenticated caller, derived from a verified Supabase JWT."""

    id: str
    email: str | None = None
    # Raw bearer token, so later modules can make RLS-scoped Supabase calls as this user.
    access_token: str


class MeResponse(BaseModel):
    id: str
    email: str | None = None


class ThreadCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class Thread(BaseModel):
    id: str
    title: str | None = None
    created_at: str
    updated_at: str | None = None


class Source(BaseModel):
    document_id: str
    filename: str
    chunk_index: int
    content: str
    similarity: float


class Message(BaseModel):
    id: str
    role: str
    content: str
    sources: list[Source] | None = None
    created_at: str


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)


class Document(BaseModel):
    id: str
    filename: str
    status: str
    error: str | None = None
    chunk_count: int = 0
    created_at: str
