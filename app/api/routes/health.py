"""健康检查接口：/health/live 和 /health/ready。"""
# ↑ 模块 docstring：提供两个健康检查接口。

# 导入 asyncio 标准库：用它的 timeout 做超时控制。
import asyncio

# 导入 logging 标准库。
import logging

# 从 FastAPI 导入 APIRouter（创建路由组）。
from fastapi import APIRouter

# 从 FastAPI 导入 JSONResponse（JSON 响应）。
from fastapi.responses import JSONResponse

# 从 SQLAlchemy 导入 text（构造原生 SQL 文本）。
from sqlalchemy import text

# 从 SQLAlchemy 导入 SQLAlchemyError（数据库相关异常的基类）。
from sqlalchemy.exc import SQLAlchemyError

# 导入依赖注入类型（路由里用它拿 Session）。
from app.api.dependencies import DbSession

# 导入配置读取函数。
from app.core.settings import get_settings

router = APIRouter(prefix="/health", tags=["health"])
# ↑ 创建健康检查路由组，所有接口前缀 /health，在文档里归到 health 分组。
logger = logging.getLogger(__name__)
# ↑ 创建本模块的日志器。


@router.get("/live")
# ↑ 声明一个 GET 接口 /health/live。
async def live() -> dict[str, str]:
    # ↑ 处理函数：返回类型是字典（FastAPI 会自动转成 JSON）。

    # 不注入数据库依赖，数据库不可用时仍然表示 HTTP 进程存活。
    # ↑ 设计说明：live 不碰数据库，只表示"进程还活着"。
    return {"status": "ok"}
    # ↑ 固定返回 {"status": "ok"}。


@router.get("/ready")
# ↑ 声明一个 GET 接口 /health/ready。
async def ready(session: DbSession) -> JSONResponse:
    # ↑ 处理函数：注入数据库 Session（DbSession），返回 JSONResponse。

    settings = get_settings()
    # ↑ 读取配置（需要 DB_SCHEMA 等）。

    try:
        # ↑ 尝试做数据库检查。
        # 超时包含取连接、建立连接和查询，不能让健康探针无限等待。
        # ↑ 设计说明：给整个检查加超时。
        async with asyncio.timeout(settings.HEALTH_TIMEOUT):
            # ↑ 限定整个检查最多 HEALTH_TIMEOUT 秒。
            await session.execute(text("SELECT 1"))
            # ↑ 执行最简单的 SQL，验证"能连上数据库并执行查询"。
            accessible = await session.scalar(
                # ↑ 执行一条 SQL 并取回单个值（True/False）。
                text(
                    # ↑ 原生 SQL 文本。
                    "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace "
                    "WHERE nspname = :schema "
                    "AND has_schema_privilege(current_user, oid, 'USAGE'))"
                    # ↑ 这条 SQL 检查：目标 Schema 是否存在，且当前账号对它
                    #   有 USAGE（使用）权限。:schema 是占位符，下面传值。
                ),
                {"schema": settings.DB_SCHEMA},
                # ↑ 把 :schema 占位符替换成配置里的 Schema 名。
            )
        if not accessible:
            # ↑ 如果 Schema 不存在或无权限……
            return JSONResponse({"status": "not_ready"}, status_code=503)
            # ↑ 返回 503（服务未就绪）。
    except (SQLAlchemyError, TimeoutError) as exc:
        # ↑ 捕获数据库错误或超时错误。
        logger.warning("readiness_failed exception_type=%s", type(exc).__name__)
        # ↑ 记一条警告日志（只记异常类型名，不记细节）。
        return JSONResponse({"status": "not_ready"}, status_code=503)
        # ↑ 返回 503。
    return JSONResponse({"status": "ok"})
    # ↑ 一切正常，返回 200 表示就绪。
