import asyncio
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
    # 不在启动时建库、建 Schema、建表或执行迁移；
    # 数据库故障由 ready 表达，live 不依赖数据库在线。
    try:
        yield
    finally:
        # 关闭连接池时给一个有限的等待时间，避免 K8s 滚动升级时容器卡在
        # `dispose()` 上无法退出。超时只记日志，不外抛泄密信息。
        try:
            async with asyncio.timeout(settings.SHUTDOWN_TIMEOUT):
                await engine.dispose()
        except TimeoutError:
            logger.warning("engine dispose timed out during shutdown")
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
#
#   RequestIdMiddleware           ← 最外：设置 request_id contextvar，给响应回写 X-Request-ID
#   └─ UnexpectedErrorMiddleware  ← 把漏出的异常转成 500，且仍然带着当前 request_id
#      └─ BodySizeLimitMiddleware ← 最内：自己消费 _BodyTooLarge 并返回 413
#         └─ ExceptionMiddleware (Starlette)
#            └─ Router
#
# 把 BodySizeLimit 放在 UnexpectedError 内层是有意为之：
# BodySizeLimit 自己 try/except _BodyTooLarge 再生成 413。
# 如果顺序反过来，_BodyTooLarge 会被 UnexpectedError 捕获并变成 500，
# 业务代码不会被调用，但状态码也错了。
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.MAX_REQUEST_BODY_BYTES)
app.add_middleware(UnexpectedErrorMiddleware)
app.add_middleware(RequestIdMiddleware)
app.include_router(health_router)
app.include_router(api_router)
