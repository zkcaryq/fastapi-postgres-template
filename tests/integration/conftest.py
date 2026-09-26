"""Integration test infrastructure.

These tests **require** a real PostgreSQL. They are skipped by default via
``addopts = -m 'not integration'`` in ``pyproject.toml``.

启用方式（任选其一）：

```powershell
# 只跑集成
INTEGRATION_DATABASE_URL=... uv run pytest -m integration

# 跑全部
INTEGRATION_DATABASE_URL=... uv run pytest -m 'integration or not integration'
```

**安全约束：**

- 集成测试只创建与清理 ``fastapi_template_test`` Schema 内的对象。
- 严禁清理任何其他 Schema / 表 / 数据库。
- 密码通过 ``INTEGRATION_DATABASE_URL`` 环境变量传入，不允许硬编码。
- 测试结束后清理失败也会尝试再次清理（fixture finalizer）。
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, text

# Windows 上 psycopg 异步不支持 ProactorEventLoop；必须显式切到 Selector。
# 在任何 pytest-asyncio 创建 loop 之前设好进程级策略。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _build_url() -> str:
    """根据 ``INTEGRATION_DATABASE_URL`` 或单变量构建连接 URL。

    优先 ``INTEGRATION_DATABASE_URL``（包含完整 DSN）。
    否则由 ``PG*`` 系列变量拼出。两者都不存在则报错。
    """
    if url := os.environ.get("INTEGRATION_DATABASE_URL"):
        return url
    pg_vars = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
    if all(os.environ.get(k) for k in pg_vars):
        return (
            f"postgresql+psycopg://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}"
            f"@{os.environ['PGHOST']}:{os.environ['PGPORT']}/{os.environ['PGDATABASE']}"
        )
    raise RuntimeError(
        "需要 INTEGRATION_DATABASE_URL 或 PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD 环境变量"
    )


@pytest.fixture(scope="session")
def integration_database_url() -> str:
    """真实 PostgreSQL 的连接 URL。"""
    return _build_url()


@pytest.fixture(scope="session")
def test_schema_name() -> str:
    """集成测试专用 Schema；所有 DDL / DML 只在此 Schema 内发生。"""
    name = os.environ.get("INTEGRATION_DB_SCHEMA", "fastapi_template_test")
    if name != "fastapi_template_test":
        raise RuntimeError(f"INTEGRATION_DB_SCHEMA 必须是 fastapi_template_test，实际 {name!r}")
    return name


@pytest.fixture(scope="session")
def admin_database_url(integration_database_url: str) -> str:
    """与 ``integration_database_url`` 同源的 AUTOCOMMIT URL，用于 DDL 探针。"""
    return integration_database_url


@pytest.fixture(scope="session")
def schema_ready(admin_database_url: str, test_schema_name: str) -> Iterator[None]:
    """session 级 fixture：确认 Schema 存在并可在测试结束时清理。

    这里**不**自动 CREATE Schema：如果 Schema 不存在，立刻 fail，
    避免 silent create + silent drop 掩盖权限问题。
    """
    engine = create_engine(admin_database_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :s)"),
                {"s": test_schema_name},
            ).scalar()
        if not exists:
            raise RuntimeError(
                f"Schema '{test_schema_name}' 不存在；需要先用 DBA 权限或 CREATE SCHEMA 创建。"
            )
    finally:
        engine.dispose()
    yield
    # 测试 session 结束；不主动 drop Schema，由调用方通过清理 fixture 处理。
    # 这样可以反复跑 session 而不必每次重建。


@pytest.fixture
def clean_schema(
    admin_database_url: str, test_schema_name: str, schema_ready: None
) -> Iterator[None]:
    """每个用例前清理 Schema 内的对象（表 / alembic_version），后再次清理。"""
    engine = create_engine(admin_database_url, isolation_level="AUTOCOMMIT")
    try:
        _drop_objects_in_schema(engine, test_schema_name)
        yield
    finally:
        _drop_objects_in_schema(engine, test_schema_name)
        engine.dispose()


def _drop_objects_in_schema(engine: Any, schema: str) -> None:
    """删除 Schema 内所有表与版本表，**不**触碰其他 Schema。"""
    with engine.connect() as conn:
        # alembic_version 可能存在也可能不存在；防御式处理。
        rows = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = :s"),
            {"s": schema},
        ).all()
        for row in rows:
            # 必须 schema 限定、表名转义；表名由数据库本身读出，按字面引号。
            conn.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{row.tablename}" CASCADE'))


@pytest.fixture(autouse=True)
def _isolate_settings_cache(
    monkeypatch: pytest.MonkeyPatch,
    integration_database_url: str,
    test_schema_name: str,
) -> Iterator[None]:
    """保证每个 integration 用例在拿到最新 Settings。

    ``tests/conftest.py`` 在 import 之前已把 ``DB_HOST`` / ``DB_PASSWORD``
    等指向单元测试占位值；这里把它们覆盖到真实 PG + ``fastapi_template_test``。
    """
    from sqlalchemy import make_url

    url = make_url(integration_database_url)
    assert url.host is not None
    assert url.username is not None
    assert url.password is not None
    assert url.database is not None

    monkeypatch.setenv("DB_HOST", url.host)
    if url.port:
        monkeypatch.setenv("DB_PORT", str(url.port))
    monkeypatch.setenv("DB_NAME", url.database)
    monkeypatch.setenv("DB_USER", url.username)
    monkeypatch.setenv("DB_PASSWORD", url.password)
    monkeypatch.setenv("DB_SCHEMA", test_schema_name)
    monkeypatch.delenv("MIGRATION_DB_USER", raising=False)
    monkeypatch.delenv("MIGRATION_DB_PASSWORD", raising=False)

    from app.core import settings as settings_module

    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()
