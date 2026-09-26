from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import get_settings

settings = get_settings()

# Engine 管理连接池，不是一条连接；每进程共享，连接按需建立。
# 多 worker 的连接上限 = worker 数 × (pool_size + max_overflow)。
# 不随意设置 pool_recycle：只有代理/防火墙有明确空闲断连要求时再配置。
engine = create_async_engine(
    settings.database_url,
    connect_args=settings.connect_args,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    echo=False,
    hide_parameters=True,
)

session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    # Session 有事务状态，不能跨请求或并发任务共享。async I/O 让数据库等待
    # 不阻塞其他请求，但不会自动让 SQL 变快，也不适合直接运行阻塞型计算。
    async with session_factory() as session:
        # Service 明确 commit；依赖只清理。关闭时未提交的事务会回滚。
        # flush：发送 SQL，仍可回滚；commit：提交事务。
        # rollback：放弃事务，恢复失败后的会话；refresh：重新查询对象属性。
        yield session
