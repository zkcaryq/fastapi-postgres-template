"""FastAPI 应用装配入口。"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes.health import router as health_router
from app.core.body_limit import BodySizeLimitMiddleware
from app.core.errors import (
    BusinessException,
    UnexpectedErrorMiddleware,
    business_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.core.logging import configure_logging
from app.core.request_id import RequestIdMiddleware
from app.core.settings import get_settings
from app.db.session import engine

settings = get_settings()
configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用关闭时限时释放连接池；启动阶段不修改数据库结构。"""

    try:
        yield
    finally:
        try:
            async with asyncio.timeout(settings.SHUTDOWN_TIMEOUT):
                await engine.dispose()
        except TimeoutError:
            logger.warning("engine dispose timed out during shutdown")
        except Exception:
            logger.exception("engine dispose failed during shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    debug=False,
    lifespan=lifespan,
    docs_url=None if settings.APP_ENV == "production" else "/docs",
    redoc_url=None,
    openapi_url=None if settings.APP_ENV == "production" else "/openapi.json",
)

# Starlette 后添加的中间件位于外层。实际请求顺序为：
# RequestId -> CORS -> UnexpectedError -> BodySizeLimit -> Router。
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.MAX_REQUEST_BODY_BYTES)
app.add_middleware(UnexpectedErrorMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.CORS_ORIGINS),
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestIdMiddleware)

# 预期错误分别交给对应处理器；未知异常继续向外传播给UnexpectedErrorMiddleware。
app.add_exception_handler(BusinessException, business_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

app.include_router(health_router)
app.include_router(api_router)
