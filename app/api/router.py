"""业务 API 汇总入口。"""

from fastapi import APIRouter

from app.api.routes.users import router as users_router

api_router = APIRouter(prefix="/api")
api_router.include_router(users_router)
