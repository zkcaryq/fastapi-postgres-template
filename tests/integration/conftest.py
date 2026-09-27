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
# ↑ 模块 docstring：集成测试的基础设施。这些测试**需要真实 PostgreSQL**，
#   默认被跳过（只有加 -m integration 才跑）。并强调了几条安全约束。

# 这个 import 让类型标注用"未来注解"（字符串形式）。
from __future__ import annotations

# 导入 asyncio、os、sys 标准库。
import asyncio
import os
import sys

# 导入 Iterator 和 Any 类型。
from collections.abc import Iterator
from typing import Any

# 导入 pytest 和 SQLAlchemy 的同步引擎、text。
import pytest
from sqlalchemy import create_engine, text

# Windows 上 psycopg 异步不支持 ProactorEventLoop；必须显式切到 Selector。
# 在任何 pytest-asyncio 创建 loop 之前设好进程级策略。
# ↑ 说明：Windows 下要先切换事件循环策略（和 app 里的 event_loop 同理）。
if sys.platform == "win32":
    # ↑ 如果是 Windows。
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # ↑ 设置 Windows 的 Selector 事件循环策略。


def _build_url() -> str:
    # ↑ 辅助函数：从环境变量构建数据库连接 URL。

    """根据 ``INTEGRATION_DATABASE_URL`` 或单变量构建连接 URL。

    优先 ``INTEGRATION_DATABASE_URL``（包含完整 DSN）。
    否则由 ``PG*`` 系列变量拼出。两者都不存在则报错。
    """
    # ↑ docstring：说明两种配置方式。
    if url := os.environ.get("INTEGRATION_DATABASE_URL"):
        # ↑ 海象运算符 := ：先取值赋给 url，如果非空就进分支。
        return url
        # ↑ 优先用完整的 URL。
    pg_vars = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
    # ↑ 定义一组 PG 变量名。
    if all(os.environ.get(k) for k in pg_vars):
        # ↑ 如果这 5 个变量都存在。
        return (
            # ↑ 拼接 URL。
            f"postgresql+psycopg://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}"
            # ↑ 用户名:密码。
            f"@{os.environ['PGHOST']}:{os.environ['PGPORT']}/{os.environ['PGDATABASE']}"
            # ↑ @主机:端口/库名。
        )
    raise RuntimeError(
        # ↑ 两种方式都没配置，报错。
        "需要 INTEGRATION_DATABASE_URL 或 PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD 环境变量"
    )


@pytest.fixture(scope="session")
# ↑ session 级 fixture：整个测试会话只执行一次。
def integration_database_url() -> str:
    # ↑ 提供真实数据库的连接 URL。

    """真实 PostgreSQL 的连接 URL。"""
    # ↑ docstring。
    return _build_url()
    # ↑ 返回构建好的 URL。


@pytest.fixture(scope="session")
# ↑ session 级。
def test_schema_name() -> str:
    # ↑ 提供测试专用 Schema 名。

    """集成测试专用 Schema；所有 DDL / DML 只在此 Schema 内发生。"""
    # ↑ docstring。
    name = os.environ.get("INTEGRATION_DB_SCHEMA", "fastapi_template_test")
    # ↑ 读取 Schema 名（默认 fastapi_template_test）。
    if name != "fastapi_template_test":
        # ↑ 如果不是预期的测试 Schema……
        raise RuntimeError(f"INTEGRATION_DB_SCHEMA 必须是 fastapi_template_test，实际 {name!r}")
        # ↑ 报错（防止误指向业务 Schema）。
    return name
    # ↑ 返回。


@pytest.fixture(scope="session")
# ↑ session 级。
def admin_database_url(integration_database_url: str) -> str:
    # ↑ 提供用于 DDL 的 URL。

    """与 ``integration_database_url`` 同源的 AUTOCOMMIT URL，用于 DDL 探针。"""
    # ↑ docstring。
    return integration_database_url
    # ↑ 直接复用同一个 URL。


@pytest.fixture(scope="session")
# ↑ session 级。
def schema_ready(admin_database_url: str, test_schema_name: str) -> Iterator[None]:
    # ↑ 确认测试 Schema 存在（但不自动创建）。

    """session 级 fixture：确认 Schema 存在并可在测试结束时清理。

    这里**不**自动 CREATE Schema：如果 Schema 不存在，立刻 fail，
    避免 silent create + silent drop 掩盖权限问题。
    """
    # ↑ docstring：故意不自动建 Schema，缺失就失败，避免掩盖权限问题。
    engine = create_engine(admin_database_url, isolation_level="AUTOCOMMIT")
    # ↑ 创建同步引擎（AUTOCOMMIT 模式，用于执行 DDL）。
    try:
        # ↑ 尝试。
        with engine.connect() as conn:
            # ↑ 建立连接。
            exists = conn.execute(
                # ↑ 查询 Schema 是否存在。
                text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :s)"),
                # ↑ 原生 SQL。
                {"s": test_schema_name},
                # ↑ 绑定参数。
            ).scalar()
            # ↑ 取回单个值（True/False）。
        if not exists:
            # ↑ 如果不存在……
            raise RuntimeError(
                # ↑ 报错。
                f"Schema '{test_schema_name}' 不存在；需要先用 DBA 权限或 CREATE SCHEMA 创建。"
            )
    finally:
        # ↑ 最后。
        engine.dispose()
        # ↑ 释放引擎。
    yield
    # ↑ 让测试继续。
    # 测试 session 结束；不主动 drop Schema，由调用方通过清理 fixture 处理。
    # 这样可以反复跑 session 而不必每次重建。
    # ↑ 说明。


@pytest.fixture
# ↑ 函数级 fixture（每个用例执行一次）。
def clean_schema(
    # ↑ 清理测试 Schema 的表。
    admin_database_url: str,
    test_schema_name: str,
    schema_ready: None,
) -> Iterator[None]:
    # ↑ 依赖 schema_ready（确保 Schema 存在）。

    """每个用例前清理 Schema 内的对象（表 / alembic_version），后再次清理。"""
    # ↑ docstring。
    engine = create_engine(admin_database_url, isolation_level="AUTOCOMMIT")
    # ↑ 创建引擎。
    try:
        # ↑ 尝试。
        _drop_objects_in_schema(engine, test_schema_name)
        # ↑ 用例前先清理。
        yield
        # ↑ 让测试执行。
    finally:
        # ↑ 最后。
        _drop_objects_in_schema(engine, test_schema_name)
        # ↑ 用例后再清理。
        engine.dispose()
        # ↑ 释放引擎。


def _drop_objects_in_schema(engine: Any, schema: str) -> None:
    # ↑ 辅助函数：删除指定 Schema 内的所有表。

    """删除 Schema 内所有表与版本表，**不**触碰其他 Schema。"""
    # ↑ docstring。
    with engine.connect() as conn:
        # ↑ 连接。
        # alembic_version 可能存在也可能不存在；防御式处理。
        # ↑ 说明。
        rows = conn.execute(
            # ↑ 查询该 Schema 下所有表名。
            text("SELECT tablename FROM pg_tables WHERE schemaname = :s"),
            # ↑ 原生 SQL。
            {"s": schema},
            # ↑ 参数。
        ).all()
        # ↑ 取所有行。
        for row in rows:
            # ↑ 遍历每张表。
            # 必须 schema 限定、表名转义；表名由数据库本身读出，按字面引号。
            # ↑ 说明。
            conn.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{row.tablename}" CASCADE'))
            # ↑ 逐张删表（带 Schema 限定和引号转义，CASCADE 级联删除）。


@pytest.fixture(autouse=True)
# ↑ autouse=True：每个集成测试用例自动使用，无需显式声明。
def _isolate_settings_cache(
    # ↑ 隔离配置缓存。
    monkeypatch: pytest.MonkeyPatch,
    integration_database_url: str,
    test_schema_name: str,
) -> Iterator[None]:
    # ↑ 让每个集成用例拿到最新的、指向真实库的 Settings。

    """保证每个 integration 用例在拿到最新 Settings。

    ``tests/conftest.py`` 在 import 之前已把 ``DB_HOST`` / ``DB_PASSWORD``
    等指向单元测试占位值；这里把它们覆盖到真实 PG + ``fastapi_template_test``。
    """
    # ↑ docstring：解释为什么要把占位配置覆盖成真实库配置。
    from sqlalchemy import make_url
    # ↑ 函数内导入 URL 解析工具。

    url = make_url(integration_database_url)
    # ↑ 解析真实 URL。
    assert url.host is not None
    # ↑ 断言主机存在。
    assert url.username is not None
    # ↑ 断言用户名存在。
    assert url.password is not None
    # ↑ 断言密码存在。
    assert url.database is not None
    # ↑ 断言库名存在。

    monkeypatch.setenv("DB_HOST", url.host)
    # ↑ 覆盖主机。
    if url.port:
        # ↑ 如果有端口。
        monkeypatch.setenv("DB_PORT", str(url.port))
        # ↑ 覆盖端口。
    monkeypatch.setenv("DB_NAME", url.database)
    # ↑ 覆盖库名。
    monkeypatch.setenv("DB_USER", url.username)
    # ↑ 覆盖用户名。
    monkeypatch.setenv("DB_PASSWORD", url.password)
    # ↑ 覆盖密码。
    monkeypatch.setenv("DB_SCHEMA", test_schema_name)
    # ↑ 覆盖 Schema。
    monkeypatch.delenv("MIGRATION_DB_USER", raising=False)
    # ↑ 删除迁移用户名（避免干扰）。
    monkeypatch.delenv("MIGRATION_DB_PASSWORD", raising=False)
    # ↑ 删除迁移密码。

    from app.core import settings as settings_module
    # ↑ 函数内导入配置模块。

    settings_module.get_settings.cache_clear()
    # ↑ 清缓存，让新配置生效。
    yield
    # ↑ 让测试执行。
    settings_module.get_settings.cache_clear()
    # ↑ 测试后再清缓存。
