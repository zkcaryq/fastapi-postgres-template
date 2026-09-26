import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.api.routes.health import router as health_router
from app.core.body_limit import BodySizeLimitMiddleware
from app.core.errors import UnexpectedErrorMiddleware
from app.core.logging import configure_logging
from app.core.request_id import RequestIdMiddleware
from app.core.settings import get_settings
from app.db.session import engine

settings = get_settings()
configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 不在启动时建库、建 Schema、建表或执行迁移；数据库故障由 ready 表达。
    # 启动读取配置会 fail fast，但建连接是惰性的，live 不依赖数据库在线。
    try:
        yield
    finally:
        # 关闭时给连接池一个有限的等待时间，避免 K8s 滚动升级时卡死。
        try:
            await engine.dispose()
        except Exception:
            logger.exception("engine dispose failed during shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    # DEBUG 仅控制内部日志；不向客户端暴露 Starlette 的调试 traceback。
    debug=False,
    lifespan=lifespan,
    docs_url=None if settings.APP_ENV == "production" else "/docs",
    redoc_url=None,
    openapi_url=None if settings.APP_ENV == "production" else "/openapi.json",
)
# 中间件顺序：最后 add 的排在最外层，请求自外向内穿过。
# 外向内依次是 RequestId → BodySizeLimit → UnexpectedError：
# RequestId 最外：之后所有日志、413 和 500 响应都带上 request_id；
# UnexpectedError 最内：异常回传时仍在 RequestId 的 contextvar 范围内，
# 若用 @app.exception_handler(Exception) 注册，处理器会落到最外层 ServerErrorMiddleware，
# 那里读到的 request_id 只会是 '-'。
app.add_middleware(UnexpectedErrorMiddleware)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.MAX_REQUEST_BODY_BYTES)
app.add_middleware(RequestIdMiddleware)
app.include_router(health_router)
app.include_router(api_router)