"""Integration 测试专用 Alembic env。

与 ``alembic/env.py`` 几乎一致，只是 ``target_metadata`` 来自
``tests.integration._models.active_metadata()`` 而非 ``app.db.base.Base.metadata``。

alembic 每次执行命令都会重新 exec 本文件，因此 ``active_metadata()`` 在每次
revision / upgrade / check 时都会重新求值——测试可以在两轮 revision 之间切换
“当前可见的 metadata”，真实模拟增量迁移。

**生产代码不应引入此文件**。它存在的唯一目的：让集成测试在不污染
``app.models`` 的前提下，验证真实 PostgreSQL 上的 Alembic 生命周期。
"""

from alembic.util import CommandError
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

from alembic import context
from app.core.settings import get_settings
from tests.integration import _models

settings = get_settings()
target_metadata = _models.active_metadata()


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name == settings.DB_SCHEMA
    if type_ == "table":
        return parent_names.get("schema_name") == settings.DB_SCHEMA
    return True


def configure(**kwargs):
    context.configure(
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        version_table_schema=settings.DB_SCHEMA,
        compare_type=True,
        **kwargs,
    )


def run_migrations_offline():
    configure(
        url=settings.migration_database_url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = create_engine(
        settings.migration_database_url,
        connect_args=settings.connect_args,
        poolclass=NullPool,
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_schema(settings.DB_SCHEMA):
                raise CommandError("目标 Schema 不存在")
            connection.rollback()
            configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


# 防御：alembic exec 本文件时 ``context`` 是可用的 EnvironmentContext；
# 若被普通 ``import``（例如 IDE 索引或误引用），跳过迁移分支避免 NameError。
if hasattr(context, "config") and hasattr(context, "run_migrations"):
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()
