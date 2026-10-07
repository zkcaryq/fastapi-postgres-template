"""User 示例路由。"""

from fastapi import APIRouter

from app.api.dependencies import DbSession
from app.core.errors import BusinessException
from app.schemas.apiresponse import ApiResponse
from app.schemas.user import UserResponse
from app.services.user import get_user_by_username

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{username}")
async def get_user(username: str, session: DbSession) -> ApiResponse:
    user = await get_user_by_username(session, username=username)
    if user is None:
        raise BusinessException(message="用户不存在", status_code=404)
    return ApiResponse.success(data=UserResponse.model_validate(user))
