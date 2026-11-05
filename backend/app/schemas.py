from pydantic import BaseModel


class CurrentUser(BaseModel):
    """The authenticated caller, derived from a verified Supabase JWT."""

    id: str
    email: str | None = None
    # Raw bearer token, so later modules can make RLS-scoped Supabase calls as this user.
    access_token: str


class MeResponse(BaseModel):
    id: str
    email: str | None = None
