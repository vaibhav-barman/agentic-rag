from typing import Literal

from pydantic import BaseModel, Field, field_validator


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
    """Where an answer came from: a document chunk or a web page."""

    type: Literal["document", "web"] = "document"
    content: str = ""
    # document sources
    document_id: str | None = None
    filename: str | None = None
    chunk_index: int | None = None
    similarity: float | None = None
    score: float | None = None
    vector_rank: int | None = None
    keyword_rank: int | None = None
    # web sources
    url: str | None = None
    title: str | None = None


class Step(BaseModel):
    """One tool call made while answering. Sub-agent steps point at their parent."""

    id: str
    name: str
    arguments: dict = Field(default_factory=dict)
    parent_id: str | None = None
    ok: bool | None = None
    summary: str | None = None
    data: dict | None = None
    # Text streamed by a sub-agent while it worked (only on analyze_document steps).
    text: str | None = None


class Message(BaseModel):
    id: str
    role: str
    content: str
    sources: list[Source] | None = None
    steps: list[Step] | None = None
    created_at: str


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)


DocumentType = Literal[
    "report", "article", "notes", "manual", "contract", "email", "resume", "spreadsheet", "other"
]


class DocumentMetadata(BaseModel):
    """Structured metadata the LLM extracts from each document at ingestion."""

    title: str = Field(description="A short title for the document.")
    summary: str = Field(description="One or two sentences on what the document contains.")
    document_type: DocumentType = Field(description="The best-fitting category.")
    topics: list[str] = Field(
        default_factory=list, description="3-6 short lowercase topic tags, e.g. 'pricing'."
    )
    language: str = Field(default="en", description="ISO 639-1 code of the main language.")
    key_entities: list[str] = Field(
        default_factory=list, description="Up to 8 important people, organisations or products."
    )
    document_date: str | None = Field(
        default=None, description="The document's own date as YYYY-MM-DD, if it states one."
    )

    @field_validator("topics")
    @classmethod
    def _clean_topics(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for topic in value:
            topic = " ".join(topic.lower().split())
            if topic and topic not in seen:
                seen.append(topic)
        return seen[:8]

    @field_validator("key_entities")
    @classmethod
    def _clean_entities(cls, value: list[str]) -> list[str]:
        return [e.strip() for e in value if e.strip()][:8]


class Document(BaseModel):
    id: str
    filename: str
    status: str
    error: str | None = None
    chunk_count: int = 0
    file_size: int | None = None
    metadata: dict = Field(default_factory=dict)
    ingest_stats: dict | None = None
    created_at: str
    updated_at: str | None = None


class UploadResult(Document):
    # created | updated | unchanged | duplicate
    action: str = "created"
