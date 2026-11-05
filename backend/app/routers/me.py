from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.schemas import CurrentUser, MeResponse

router = APIRouter()


@router.get("/me", response_model=MeResponse)
def read_me(user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    return MeResponse(id=user.id, email=user.email)
