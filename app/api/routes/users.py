"""User 示例路由。"""

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import DbSession
from app.schemas.user import UserResponse
from app.services.user import get_user_by_username

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{username}", response_model=UserResponse)
async def get_user(username: str, session: DbSession) -> UserResponse:
    user = await get_user_by_username(session, username=username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.model_validate(user)
