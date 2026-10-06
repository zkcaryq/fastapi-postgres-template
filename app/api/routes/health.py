"""进程存活检查与数据库就绪检查。"""

import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import DbSession
from app.core.settings import get_settings

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/live")
async def live() -> dict[str, str]:
    """只检查 FastAPI 进程，不依赖数据库。"""

    return {"status": "alive"}


@router.get("/ready")
async def ready(session: DbSession) -> JSONResponse:
    """在规定时间内执行 SELECT 1，确认数据库可以处理请求。"""

    try:
        async with asyncio.timeout(get_settings().HEALTH_TIMEOUT):
            await session.scalar(text("SELECT 1"))
    except (SQLAlchemyError, TimeoutError):
        logger.exception("database readiness check failed")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ready"})
