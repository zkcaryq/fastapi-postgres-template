"""API 挂载入口。

模板本身不包含任何业务路由。新模块在这里
``api_router.include_router(xxx_router)``。
"""

from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")
