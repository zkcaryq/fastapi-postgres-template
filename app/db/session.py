"""数据库引擎、连接池、Session 工厂与依赖注入。"""
# ↑ 模块 docstring：这个文件负责"和数据库建立连接"的所有基础设施。

# 从 collections.abc 导入 AsyncIterator（异步迭代器类型，用于标注依赖函数）。
from collections.abc import AsyncIterator

# 导入 SQLAlchemy 异步三件套：
#   AsyncSession 异步会话、async_sessionmaker 会话工厂、create_async_engine 异步引擎。
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 导入配置读取函数。
from app.core.settings import get_settings

settings = get_settings()
# ↑ 读取配置单例。

# Engine 管理连接池，不是一条连接；每进程共享，连接按需建立。
# 多 worker 的连接上限 = worker 数 × (pool_size + max_overflow)。
# 不随意设置 pool_recycle：只有代理/防火墙有明确空闲断连要求时再配置。
# ↑ 设计说明：解释"引擎"和"连接池"的关系。
engine = create_async_engine(
    # ↑ 创建异步数据库引擎。
    settings.database_url,
    # ↑ 数据库连接 URL（用户名/密码/地址等，来自配置）。
    connect_args=settings.connect_args,
    # ↑ 连接时附加的参数（超时、SSL、search_path 等，来自配置）。
    pool_pre_ping=True,
    # ↑ 从池里取出连接前先"探活"，防止用到已经断开的连接。
    pool_size=settings.DB_POOL_SIZE,
    # ↑ 连接池常驻连接数。
    max_overflow=settings.DB_MAX_OVERFLOW,
    # ↑ 连接池可临时超出的连接数。
    pool_timeout=settings.DB_POOL_TIMEOUT,
    # ↑ 从池里取连接的最长等待时间（秒）。
    echo=False,
    # ↑ 不打印每条 SQL（调试时才开）。
    hide_parameters=True,
    # ↑ 即使报错，也不在日志里显示 SQL 参数值（防止泄露敏感数据）。
)

# AsyncSession 推荐配置：
# - expire_on_commit=False：commit 后访问普通属性不再触发隐式数据库 IO。
#   文档里不要再说"必须"；这是配合 async 上下文读取的常见推荐值之一。
# - autoflush=False：把"什么时候发 SQL"交回给业务代码。
#   session.add() 之后，**必须**显式 await session.flush() 才能让同一事务里
#   的后续 SELECT 看到这一写入。这条约束不要让新开发者以为 add() 会自动可见。
# ↑ 设计说明：解释两个关键配置。
session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
# ↑ 创建一个 Session 工厂。之后每次调用它，就得到一个全新的 Session。
#   expire_on_commit=False：提交后访问对象属性不再偷偷查库。
#   autoflush=False：不自动 flush，把"何时发 SQL"交给业务代码显式控制。


async def get_db_session() -> AsyncIterator[AsyncSession]:
    # ↑ 依赖注入函数：FastAPI 会在需要 Session 时调用它。
    #   返回类型是 AsyncIterator（异步迭代器），配合 yield 使用。

    # Session 有事务状态，不能跨请求或并发任务共享。async I/O 让数据库等待
    # 不阻塞其他请求，但不会自动让 SQL 变快，也不适合直接运行阻塞型计算。
    # ↑ 设计说明：解释 Session 的生命周期和异步的本质。
    async with session_factory() as session:
        # ↑ 用工厂创建一个 Session，并用 async with 管理它的关闭。
        # Service 明确 commit；依赖只清理。关闭时未提交的事务会回滚。
        # flush：发送 SQL，仍可回滚；commit：提交事务。
        # rollback：放弃事务，恢复失败后的会话；refresh：重新查询对象属性。
        # ↑ 设计说明：这里只管"创建和清理"，不管 commit（提交由 Service 负责）。
        yield session
        # ↑ 把 Session 交给使用方（路由函数）。请求处理完后，代码回到这里，
        #   退出 async with 时自动关闭 Session（未提交的事务会被回滚）。
