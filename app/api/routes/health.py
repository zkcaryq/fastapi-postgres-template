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
    # 不注入数据库依赖，数据库不可用时仍然表示 HTTP 进程存活。
    return {"status": "ok"}


@router.get("/ready", response_model=None)
async def ready(session: DbSession) -> JSONResponse:
    settings = get_settings()
    try:
        # 超时包含取连接、建立连接和查询，不能让健康探针无限等待。
        async with asyncio.timeout(settings.HEALTH_TIMEOUT):
            await session.execute(text("SELECT 1"))
            accessible = await session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace "
                    "WHERE nspname = :schema "
                    "AND has_schema_privilege(current_user, oid, 'USAGE'))"
                ),
                {"schema": settings.DB_SCHEMA},
            )
        if not accessible:
            return JSONResponse({"status": "not_ready"}, status_code=503)
    except (SQLAlchemyError, TimeoutError) as exc:
        logger.warning("readiness_failed exception_type=%s", type(exc).__name__)
        return JSONResponse({"status": "not_ready"}, status_code=503)
    return JSONResponse({"status": "ok"})
