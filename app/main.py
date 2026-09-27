"""应用入口：创建 FastAPI 实例、挂载中间件和路由、定义启动/关闭逻辑。"""
# ↑ 模块 docstring：这个文件是"应用的总装配车间"。

# 导入 asyncio 标准库：提供 asyncio.timeout 等异步工具。
import asyncio

# 导入 logging 标准库。
import logging

# 从 contextlib 导入 asynccontextmanager：用于把异步函数变成"上下文管理器"（见 lifespan）。
from contextlib import asynccontextmanager

# 从 FastAPI 导入核心类 FastAPI。
from fastapi import FastAPI

# 从项目各模块导入需要装配的零件：
from app.api.router import api_router

# ↑ 业务 API 汇总路由（前缀 /api/v1）。
from app.api.routes.health import router as health_router

# ↑ 健康检查路由（/health/live、/health/ready）。
from app.core.body_limit import BodySizeLimitMiddleware

# ↑ 请求体大小限制中间件。
from app.core.errors import UnexpectedErrorMiddleware

# ↑ 未捕获异常兜底中间件。
from app.core.logging import configure_logging

# ↑ 日志配置函数。
from app.core.request_id import RequestIdMiddleware

# ↑ 请求 ID 中间件。
from app.core.settings import get_settings

# ↑ 配置读取函数。
from app.db.session import engine

# ↑ 数据库引擎（管理连接池）。

settings = get_settings()
# ↑ 读取配置单例（此时会读 .env 并校验，Fail Fast）。
configure_logging()
# ↑ 配置日志（必须在打日志之前调用）。
logger = logging.getLogger(__name__)
# ↑ 创建本模块的日志器。


@asynccontextmanager
# ↑ 装饰器：把下面的异步生成器函数变成"异步上下文管理器"。
#   通俗理解：lifespan 是"应用的一生"——启动时执行 yield 之前的代码，
#   关闭时执行 yield 之后的代码。
async def lifespan(app: FastAPI):
    # ↑ 参数 app 是 FastAPI 实例（框架会自动传进来）。

    # 不在启动时建库、建 Schema、建表或执行迁移；
    # 数据库故障由 ready 表达，live 不依赖数据库在线。
    # ↑ 设计说明：启动时不碰数据库结构（建表等交给 Alembic 迁移）。
    try:
        # ↑ 进入启动阶段。
        yield
        # ↑ 这里暂停，把控制权交给应用运行。应用运行期间，代码停在这一行。
        #   直到应用要关闭时，才会继续往下走 finally。
    finally:
        # ↑ 关闭阶段：无论如何（正常或异常关闭）都要执行。
        # 关闭连接池时给一个有限的等待时间，避免 K8s 滚动升级时容器卡在
        # `dispose()` 上无法退出。超时只记日志，不外抛泄密信息。
        # ↑ 设计说明：关闭连接池要限时，防止卡死。
        try:
            # ↑ 尝试关闭连接池。
            async with asyncio.timeout(settings.SHUTDOWN_TIMEOUT):
                # ↑ 限定最多等 SHUTDOWN_TIMEOUT 秒。
                await engine.dispose()
                # ↑ 释放数据库连接池（关闭所有连接）。
        except TimeoutError:
            # ↑ 如果超时了……
            logger.warning("engine dispose timed out during shutdown")
            # ↑ 只记一条警告，不抛出（让进程能顺利退出）。
        except Exception:
            # ↑ 如果发生其他错误……
            logger.exception("engine dispose failed during shutdown")
            # ↑ 记录异常，同样不抛出。


app = FastAPI(
    # ↑ 创建 FastAPI 应用实例。
    title=settings.APP_NAME,
    # ↑ 应用标题（显示在 /docs 文档页上）。
    # DEBUG 仅控制内部日志；不向客户端暴露 Starlette 的调试 traceback。
    debug=False,
    # ↑ 硬编码为 False：即使开了 DEBUG 配置，也不给客户端看调试堆栈（安全）。
    lifespan=lifespan,
    # ↑ 挂载上面的启动/关闭逻辑。
    docs_url=None if settings.APP_ENV == "production" else "/docs",
    # ↑ 生产环境禁用 /docs 文档页（安全），其他环境开放。
    redoc_url=None,
    # ↑ 禁用 ReDoc 文档页（只保留 Swagger 的 /docs）。
    openapi_url=None if settings.APP_ENV == "production" else "/openapi.json",
    # ↑ 生产环境同时禁用 openapi.json 接口描述（和 /docs 配套）。
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
# ↑ 上面的注释详细解释了中间件的顺序（阶段 8 的核心内容）。

app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.MAX_REQUEST_BODY_BYTES)
# ↑ 添加请求体限制中间件，上限字节数从配置读取。
app.add_middleware(UnexpectedErrorMiddleware)
# ↑ 添加异常兜底中间件。
app.add_middleware(RequestIdMiddleware)
# ↑ 添加请求 ID 中间件。注意：后 add 的在最外层，所以 RequestId 在最外。
app.include_router(health_router)
# ↑ 挂载健康检查路由（不设前缀，路径就是 /health/live 等）。
app.include_router(api_router)
# ↑ 挂载业务 API 路由（前缀 /api/v1）。
