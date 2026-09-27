"""Alembic 迁移环境：这是 alembic 每次执行命令时都会运行的脚本。

当你运行 `alembic revision`、`alembic upgrade`、`alembic check` 等命令时，
Alembic 会先执行这个文件，用它来知道：连哪个数据库、用哪套模型、怎么跑迁移。
"""
# ↑ 模块 docstring：解释这个文件在 Alembic 迁移流程中的角色（阶段 3 的核心）。

# 从 Alembic 导入 CommandError（Alembic 命令错误异常）。
from alembic.util import CommandError

# 从 SQLAlchemy 导入 create_engine（同步引擎）和 inspect（检查数据库结构）。
from sqlalchemy import create_engine, inspect

# 从 SQLAlchemy 导入 NullPool（"不维护连接池"的连接池类型，适合短命令）。
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401  # 导入包才会执行各 Model 定义，注册到 metadata

# ↑ 关键的一行！导入 app.models 包，会触发包里的 __init__.py 执行，
#   而 __init__.py 里显式 import 了所有 Model，从而把表注册到 Base.metadata。
#   # noqa: F401 是告诉 lint 工具"这个 import 确实没被直接使用，但别报错"。
from alembic import context

# ↑ 导入 Alembic 的 context（迁移的"执行上下文"，含配置和命令参数）。
from app.core.logging import configure_logging

# ↑ 导入日志配置函数。
from app.core.settings import get_settings

# ↑ 导入配置读取函数。
from app.db.alembic_guard import reject_empty_metadata

# ↑ 导入"空 metadata 护栏"函数（防止没注册模型就误跑迁移）。
from app.db.base import Base

# ↑ 导入 ORM 基类（它的 metadata 里登记了所有表）。

settings = get_settings()
# ↑ 读取配置单例。
configure_logging()
# ↑ 配置日志。
target_metadata = Base.metadata
# ↑ 关键：把"代码里定义的表结构"交给 Alembic，让它拿去和数据库实际结构对比，
#   从而自动生成迁移差异。


def include_name(name, type_, parent_names):
    # ↑ 过滤函数：决定迁移时哪些 Schema/表要"纳入考虑"。

    # 连接的 search_path 固定为 pg_catalog；目标 Schema 显式限定，避免 public
    # 或与账号同名的 Schema 被当作默认 Schema 后重复反射。
    # ↑ 设计说明：因为连接时 search_path 设成了 pg_catalog，所以要显式
    #   只认目标 Schema，防止把其他 Schema 的表也反射进来。
    if type_ == "schema":
        # ↑ 如果当前判断的对象是"Schema"……
        return name == settings.DB_SCHEMA
        # ↑ 只保留与配置一致的 Schema。
    if type_ == "table":
        # ↑ 如果当前判断的对象是"表"……
        return parent_names.get("schema_name") == settings.DB_SCHEMA
        # ↑ 只保留属于目标 Schema 的表。
    return True
    # ↑ 其他类型的对象（如列、索引）默认都保留。


def _process_revision_directives(migration_context, revision, directives):
    # ↑ 钩子函数：在生成迁移前被调用，用来做"护栏检查"。

    reject_empty_metadata(
        # ↑ 调用护栏：检查是否一张表都没注册。
        autogenerate=getattr(context.config.cmd_opts, "autogenerate", False),
        # ↑ 从命令参数里取"是否是自动生成模式"。
        tables=target_metadata.tables,
        # ↑ 传入当前注册的所有表。
    )


def configure(**kwargs):
    # ↑ 配置迁移环境的函数（在线/离线模式都会调用）。

    context.configure(
        # ↑ 配置 Alembic 的迁移上下文。
        target_metadata=target_metadata,
        # ↑ 对比的目标：代码里的表结构。
        include_schemas=True,
        # ↑ 处理时要考虑 Schema。
        include_name=include_name,
        # ↑ 用上面的 include_name 过滤要处理的 Schema/表。
        # 版本表与业务表位于同一明确指定的 Schema；不存在时不偷偷创建。
        version_table_schema=settings.DB_SCHEMA,
        # ↑ 版本表（alembic_version）也放在目标 Schema 里。
        compare_type=True,
        # ↑ 对比时也检查列的类型变化（不只是增删列）。
        process_revision_directives=_process_revision_directives,
        # ↑ 挂上护栏钩子。
        **kwargs,
        # ↑ 把调用方额外传入的参数（如连接、URL）原样传进去。
    )


def run_migrations_offline():
    # ↑ 离线模式：不连数据库，只把迁移 SQL 生成出来（输出到屏幕或文件）。

    # 离线模式同样使用迁移账号：避免本地用应用账号生成的 SQL 上到生产失败。
    # ↑ 设计说明：离线生成 SQL 也用迁移账号，保证生成的 SQL 权限一致。
    configure(
        # ↑ 配置迁移环境。
        url=settings.migration_database_url,
        # ↑ 传入迁移账号的数据库 URL。
        literal_binds=True,
        # ↑ 把参数值直接"内联"进 SQL（因为不连库，无法用占位符）。
        dialect_opts={"paramstyle": "named"},
        # ↑ 指定 SQL 参数风格为命名参数。
    )
    with context.begin_transaction():
        # ↑ 开启一个"事务上下文"（离线模式是模拟的）。
        context.run_migrations()
        # ↑ 执行迁移（生成 SQL 输出）。


def run_migrations_online():
    # ↑ 在线模式：真实连数据库，直接执行迁移。

    # 独立短命令使用同步 Engine + NullPool，无须引入异步迁移复杂度。
    # ↑ 设计说明：迁移是短暂的一次性命令，用同步引擎 + 不维护连接池，简单高效。
    engine = create_engine(
        # ↑ 创建同步数据库引擎。
        settings.migration_database_url,
        # ↑ 用迁移账号的 URL。
        connect_args=settings.connect_args,
        # ↑ 连接参数（超时、SSL、search_path 等）。
        poolclass=NullPool,
        # ↑ 不维护连接池（用完就关）。
        hide_parameters=True,
        # ↑ 报错时不显示 SQL 参数。
    )
    try:
        # ↑ 尝试执行迁移。
        with engine.connect() as connection:
            # ↑ 建立一条数据库连接。
            if not inspect(connection).has_schema(settings.DB_SCHEMA):
                # ↑ 检查目标 Schema 是否存在（inspect 用于查看数据库结构）。
                raise CommandError("目标 Schema 不存在；请先由你或 DBA 创建，再填写 DB_SCHEMA。")
                # ↑ 不存在就报错（模板不自动建 Schema）。
            # 反射检查启动了事务；结束只读事务后，迁移才能正确拥有自己的事务。
            # ↑ 设计说明：上面的 has_schema 检查开启了事务，要先结束它。
            connection.rollback()
            # ↑ 回滚（结束）刚才检查开启的只读事务。
            configure(connection=connection)
            # ↑ 用这条连接配置迁移环境。
            with context.begin_transaction():
                # ↑ 开启迁移事务。
                context.run_migrations()
                # ↑ 执行迁移。
    finally:
        # ↑ 无论成功失败，最后都要执行。
        engine.dispose()
        # ↑ 释放引擎（关闭连接）。


if context.is_offline_mode():
    # ↑ 判断当前是否离线模式（比如 `alembic upgrade --sql` 会进离线模式）。
    run_migrations_offline()
    # ↑ 是离线：跑离线逻辑。
else:
    # ↑ 否则……
    run_migrations_online()
    # ↑ 跑在线逻辑。
