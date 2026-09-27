"""Integration 测试专用 Alembic env。

与 ``alembic/env.py`` 几乎一致，只是 ``target_metadata`` 来自
``tests.integration._models.active_metadata()`` 而非 ``app.db.base.Base.metadata``。

alembic 每次执行命令都会重新 exec 本文件，因此 ``active_metadata()`` 在每次
revision / upgrade / check 时都会重新求值——测试可以在两轮 revision 之间切换
"当前可见的 metadata"，真实模拟增量迁移。

**生产代码不应引入此文件**。它存在的唯一目的：让集成测试在不污染
``app.models`` 的前提下，验证真实 PostgreSQL 上的 Alembic 生命周期。
"""
# ↑ 模块 docstring：这是集成测试专用的 Alembic 环境，和正式的 alembic/env.py 几乎一样，
#   唯一区别是"对比的表集合"可以动态切换（用于模拟增量迁移）。

# 导入 Alembic 的命令错误、SQLAlchemy 的引擎/检查器、NullPool。
from alembic.util import CommandError
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

# 导入 Alembic context、配置函数、测试模型模块。
from alembic import context
from app.core.settings import get_settings
from tests.integration import _models

settings = get_settings()
# ↑ 读取配置。
target_metadata = _models.active_metadata()
# ↑ 关键区别：用"动态可切换"的表集合，而不是正式代码的固定 Base.metadata。


def include_name(name, type_, parent_names):
    # ↑ 过滤函数：只认目标 Schema（和正式 env.py 一致）。

    if type_ == "schema":
        # ↑ 判断 Schema 对象。
        return name == settings.DB_SCHEMA
        # ↑ 只保留目标 Schema。
    if type_ == "table":
        # ↑ 判断表对象。
        return parent_names.get("schema_name") == settings.DB_SCHEMA
        # ↑ 只保留目标 Schema 里的表。
    return True
    # ↑ 其他对象默认保留。


def configure(**kwargs):
    # ↑ 配置迁移环境。

    context.configure(
        # ↑ 配置 Alembic。
        target_metadata=target_metadata,
        # ↑ 对比的表集合。
        include_schemas=True,
        # ↑ 考虑 Schema。
        include_name=include_name,
        # ↑ 用上面的过滤函数。
        version_table_schema=settings.DB_SCHEMA,
        # ↑ 版本表也放目标 Schema。
        compare_type=True,
        # ↑ 对比列类型变化。
        **kwargs,
        # ↑ 透传额外参数。
    )


def run_migrations_offline():
    # ↑ 离线模式。

    configure(
        # ↑ 配置。
        url=settings.migration_database_url,
        # ↑ URL。
        literal_binds=True,
        # ↑ 内联参数。
        dialect_opts={"paramstyle": "named"},
        # ↑ 参数风格。
    )
    with context.begin_transaction():
        # ↑ 开启事务上下文。
        context.run_migrations()
        # ↑ 执行迁移。


def run_migrations_online():
    # ↑ 在线模式。

    engine = create_engine(
        # ↑ 创建同步引擎。
        settings.migration_database_url,
        # ↑ URL。
        connect_args=settings.connect_args,
        # ↑ 连接参数。
        poolclass=NullPool,
        # ↑ 不维护连接池。
        hide_parameters=True,
        # ↑ 不显示参数。
    )
    try:
        # ↑ 尝试。
        with engine.connect() as connection:
            # ↑ 连接。
            if not inspect(connection).has_schema(settings.DB_SCHEMA):
                # ↑ 检查 Schema 是否存在。
                raise CommandError("目标 Schema 不存在")
                # ↑ 不存在就报错。
            connection.rollback()
            # ↑ 回滚（结束检查事务）。
            configure(connection=connection)
            # ↑ 用这条连接配置。
            with context.begin_transaction():
                # ↑ 开启事务。
                context.run_migrations()
                # ↑ 执行迁移。
    finally:
        # ↑ 最后。
        engine.dispose()
        # ↑ 释放引擎。


# 防御：alembic exec 本文件时 ``context`` 是可用的 EnvironmentContext；
# 若被普通 ``import``（例如 IDE 索引或误引用），跳过迁移分支避免 NameError。
# ↑ 说明：只有真正被 alembic 执行时才跑迁移，避免被普通 import 时出错。
if hasattr(context, "config") and hasattr(context, "run_migrations"):
    # ↑ 检查 context 是否是可执行的迁移上下文。
    if context.is_offline_mode():
        # ↑ 离线模式？
        run_migrations_offline()
        # ↑ 跑离线。
    else:
        # ↑ 否则。
        run_migrations_online()
        # ↑ 跑在线。
