"""连接层参数在真实 PostgreSQL 上的验证。

覆盖：
- ``SHOW search_path`` = ``pg_catalog``（模板核心安全设定）
- ``SHOW statement_timeout`` 与 ``Settings.DB_STATEMENT_TIMEOUT_MS`` 一致
- ``SHOW idle_in_transaction_session_timeout`` 与
  ``Settings.DB_IDLE_IN_TX_TIMEOUT_MS`` 一致
- idle-in-transaction 超时**真实行为**：用测试专用短超时值，
  事务内空闲超过阈值后服务器主动断开连接（不动数据库全局配置）
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration


def _parse_pg_duration_ms(value: str) -> int:
    """解析 PostgreSQL ``SHOW`` 返回的时长（如 ``30000ms`` / ``60s`` / ``1min``）。"""
    v = value.strip()
    if v.endswith("ms"):
        return int(v[:-2])
    if v.endswith("min"):
        return int(v[:-3]) * 60_000
    if v.endswith("s"):
        return int(v[:-1]) * 1_000
    return int(v)


def _engine_with_overrides(database_url: str, **overrides_ms: int):
    """基于生产 ``connect_args`` 构造 engine，可覆盖个别超时（仅本连接生效）。"""
    from app.core.settings import get_settings

    settings = get_settings()
    connect_args = dict(settings.connect_args)
    options = connect_args["options"]
    for key, value in overrides_ms.items():
        # options 形如 "-csearch_path=pg_catalog -ctimezone=UTC -cstatement_timeout=30000 ..."
        parts = options.split(" ")
        parts = [p if not p.startswith(f"-c{key}=") else f"-c{key}={value}" for p in parts]
        options = " ".join(parts)
    connect_args["options"] = options
    return create_async_engine(database_url, connect_args=connect_args)


def test_search_path_is_pg_catalog_on_production_connect_args(integration_database_url: str):
    from app.core.settings import get_settings

    settings = get_settings()
    engine = create_engine(integration_database_url, connect_args=settings.connect_args)
    try:
        with engine.connect() as conn:
            sp = conn.execute(text("SHOW search_path")).scalar()
        assert sp.split(",")[0].strip() == "pg_catalog", sp
    finally:
        engine.dispose()


def test_statement_timeout_matches_settings(integration_database_url: str):
    from app.core.settings import get_settings

    settings = get_settings()
    engine = create_engine(integration_database_url, connect_args=settings.connect_args)
    try:
        with engine.connect() as conn:
            value = conn.execute(text("SHOW statement_timeout")).scalar()
        assert _parse_pg_duration_ms(value) == settings.DB_STATEMENT_TIMEOUT_MS, value
    finally:
        engine.dispose()


def test_idle_in_transaction_timeout_matches_settings(integration_database_url: str):
    from app.core.settings import get_settings

    settings = get_settings()
    engine = create_engine(integration_database_url, connect_args=settings.connect_args)
    try:
        with engine.connect() as conn:
            value = conn.execute(text("SHOW idle_in_transaction_session_timeout")).scalar()
        assert _parse_pg_duration_ms(value) == settings.DB_IDLE_IN_TX_TIMEOUT_MS, value
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_idle_in_transaction_timeout_terminates_idle_transaction(
    integration_database_url: str,
):
    """真实行为：事务打开后空闲超过阈值，PostgreSQL 主动终止连接。

    使用测试专用短超时（1000ms），只影响本测试的连接；
    不执行 ALTER SYSTEM、不改 postgresql.conf。
    """
    eng = _engine_with_overrides(integration_database_url, idle_in_transaction_session_timeout=1000)
    session_factory = async_sessionmaker(eng, expire_on_commit=False, autoflush=False)
    try:
        with pytest.raises(DBAPIError) as excinfo:
            async with session_factory() as session, session.begin():
                await session.execute(text("SELECT 1"))
                # 事务保持打开但空闲 2 秒，超过 1000ms 阈值
                await asyncio.sleep(2.0)
                # 下一条语句应发现连接已被服务器终止
                await session.execute(text("SELECT 2"))
        msg = str(excinfo.value).lower()
        assert "idle-in-transaction" in msg or "terminating connection" in msg, msg
    finally:
        await eng.dispose()
