from alembic import context
from alembic.util import CommandError
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

import app.models  # 导入包才会执行各 Model 定义，注册到 metadata
from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.base import Base

settings = get_settings()
configure_logging()
target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    # 连接的 search_path 固定为 pg_catalog；目标 Schema 显式限定，避免 public
    # 或与账号同名的 Schema 被当作默认 Schema 后重复反射。
    if type_ == "schema":
        return name == settings.DB_SCHEMA
    if type_ == "table":
        return parent_names.get("schema_name") == settings.DB_SCHEMA
    return True


def reject_empty_metadata(migration_context, revision, directives):
    # 忘记注册 Model 时，空 metadata 可能把已有表误判为删除。
    # 只防止自动生成；手写迁移和空模板的 current / heads 不受影响。
    if getattr(context.config.cmd_opts, "autogenerate", False) and not target_metadata.tables:
        raise CommandError("没有注册 Model；请先在 app/models/__init__.py 显式导入。")


def configure(**kwargs):
    context.configure(
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        # 版本表与业务表位于同一明确指定的 Schema；不存在时不偷偷创建。
        version_table_schema=settings.DB_SCHEMA,
        compare_type=True,
        process_revision_directives=reject_empty_metadata,
        **kwargs,
    )


def run_migrations_offline():
    configure(
        url=settings.database_url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    # 独立短命令使用同步 Engine + NullPool，无须引入异步迁移复杂度。
    engine = create_engine(
        settings.database_url,
        connect_args=settings.connect_args,
        poolclass=NullPool,
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_schema(settings.DB_SCHEMA):
                raise CommandError("目标 Schema 不存在；请先由你或 DBA 创建，再填写 DB_SCHEMA。")
            # 反射检查启动了事务；结束只读事务后，迁移才能正确拥有自己的事务。
            connection.rollback()
            configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
