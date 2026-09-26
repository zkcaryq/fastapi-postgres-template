"""真实 PostgreSQL 上的 AsyncSession 行为验证。

覆盖：
- ``session.add()`` 不会自动 flush：同事务 SELECT 看不到新增行
- ``session.flush()`` 之后能看到，Identity 主键已就位
- ``session.commit()`` 之后普通属性不再触发隐式 IO（expire_on_commit=False）
- 事务 ``rollback()``：失败后所有改动消失
- 真 ``statement_timeout``：``pg_sleep(2)`` 在 1000ms 超时下被取消
"""

from __future__ import annotations

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.integration._models import IntegrationEntity

pytestmark = pytest.mark.integration


def _make_async_engine(database_url: str, statement_timeout_ms: int | None = None):
    """构造一个真实的 AsyncEngine；``statement_timeout`` 可调。"""
    from app.core.settings import get_settings

    settings = get_settings()
    connect_args = dict(settings.connect_args)
    if statement_timeout_ms is not None:
        # 覆盖默认 ``statement_timeout``，仅供本次测试。
        new_options = []
        for opt in connect_args["options"].split(" -c"):
            if opt.startswith("statement_timeout="):
                new_options.append(f"statement_timeout={statement_timeout_ms}")
            elif opt:
                new_options.append(opt)
        connect_args["options"] = " -c".join(new_options)

    return create_async_engine(database_url, connect_args=connect_args)


@pytest.fixture
async def populated_db(integration_database_url, clean_schema):
    """建表 + 写一条记录，关闭引擎后清理。"""
    from tests.integration._models import IntegrationBase, IntegrationEntity

    eng = _make_async_engine(integration_database_url)
    session_factory = async_sessionmaker(eng, expire_on_commit=False, autoflush=False)
    try:
        async with eng.begin() as conn:
            await conn.run_sync(IntegrationBase.metadata.create_all)

        async with session_factory() as session:
            await session.execute(insert(IntegrationEntity).values(name="Initial", code="INIT-1"))
            await session.commit()

        yield eng, session_factory

        async with eng.begin() as conn:
            await conn.run_sync(IntegrationBase.metadata.drop_all)
    finally:
        await eng.dispose()


# ---------------------------------------------------------------------------
# autoflush=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_add_does_not_flush_implicitly(integration_database_url, populated_db):
    """``session.add()`` 之后同事务 SELECT 看不到新行（autoflush=False）。"""
    _, session_factory = populated_db
    async with session_factory() as session:
        async with session.begin():
            new = IntegrationEntity(name="Buffered", code="BUF-1")
            session.add(new)
            # 没 flush；同事务 SELECT 应看不到
            count_before = (
                await session.execute(
                    select(IntegrationEntity).where(IntegrationEntity.code == "BUF-1")
                )
            ).all()
            assert count_before == []
        await session.rollback()


@pytest.mark.asyncio
async def test_session_flush_makes_row_visible_and_assigns_identity_pk(
    integration_database_url, populated_db
):
    """``flush()`` 之后行可见，且 Identity 主键已被数据库填充。"""
    _, session_factory = populated_db
    async with session_factory() as session:
        async with session.begin():
            new = IntegrationEntity(name="Flushed", code="FLU-1")
            session.add(new)
            # flush 之前主键是 None
            assert new.id is None
            await session.flush()
            # flush 之后主键已被分配
            assert new.id is not None
            assert new.id > 0
            # 同事务 SELECT 可见
            rows = (
                await session.execute(
                    select(IntegrationEntity).where(IntegrationEntity.code == "FLU-1")
                )
            ).all()
            assert len(rows) == 1
        await session.rollback()


# ---------------------------------------------------------------------------
# expire_on_commit=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_does_not_trigger_implicit_io_on_loaded_attrs(
    integration_database_url, populated_db
):
    """commit 之后访问已加载属性不应触发隐式 SQL（expire_on_commit=False）。"""
    _, session_factory = populated_db
    async with session_factory() as session:
        async with session.begin():
            # 先查出来，构造已加载对象
            stmt = select(IntegrationEntity).where(IntegrationEntity.code == "INIT-1")
            entity = (await session.execute(stmt)).scalars().first()
            assert entity is not None
            entity.name = "Renamed"
        # commit 已发生；再读 ``entity.name`` 不应触发 SELECT
        # 如果触发，会被 SQLAlchemy 报错（async + 隐式 IO）。
        # 这是 expire_on_commit=False 的真实可验证效果。
        assert entity.name == "Renamed"


# ---------------------------------------------------------------------------
# transaction rollback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_undoes_inserts(integration_database_url, populated_db):
    """事务内 INSERT A / INSERT B / 制造异常 / ROLLBACK → 全部消失。"""
    _, session_factory = populated_db
    eng, _ = populated_db
    async with session_factory() as session:
        try:
            async with session.begin():
                await session.execute(insert(IntegrationEntity).values(name="A", code="ROLL-A"))
                await session.execute(insert(IntegrationEntity).values(name="B", code="ROLL-B"))
                # 故意触发异常
                raise RuntimeError("boom")
        except RuntimeError:
            await session.rollback()

    async with eng.connect() as conn:
        a = (
            await conn.execute(select(IntegrationEntity).where(IntegrationEntity.code == "ROLL-A"))
        ).all()
        b = (
            await conn.execute(select(IntegrationEntity).where(IntegrationEntity.code == "ROLL-B"))
        ).all()
    assert a == []
    assert b == []


@pytest.mark.asyncio
async def test_commit_persists(integration_database_url, populated_db):
    """``commit`` 之后数据真实落库。"""
    eng, session_factory = populated_db
    async with session_factory() as session, session.begin():
        await session.execute(insert(IntegrationEntity).values(name="Committed", code="COM-1"))

    async with eng.connect() as conn:
        rows = (
            await conn.execute(select(IntegrationEntity).where(IntegrationEntity.code == "COM-1"))
        ).all()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# statement_timeout 真的会让 pg_sleep 被取消
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_statement_timeout_cancels_pg_sleep(integration_database_url, populated_db):
    """在 ``statement_timeout=1000ms`` 下 ``pg_sleep(2)`` 必须被 PG 主动取消。"""
    from sqlalchemy.exc import DBAPIError

    # 1000ms 超时；调用 pg_sleep(2) 会触发 ``canceling statement due to statement timeout``
    eng = _make_async_engine(integration_database_url, statement_timeout_ms=1000)
    try:
        async with eng.connect() as conn:
            with pytest.raises(DBAPIError) as exc:
                await conn.execute(text("SELECT pg_sleep(2)"))
        # 错误信息里应有超时关键字
        msg = str(exc.value).lower()
        assert "cancel" in msg or "timeout" in msg, msg
    finally:
        await eng.dispose()


@pytest.mark.asyncio
async def test_session_rollback_after_statement_timeout(integration_database_url, populated_db):
    """statement timeout 后 Session 必须能 rollback 回到可用状态。"""
    from sqlalchemy.exc import DBAPIError

    eng = _make_async_engine(integration_database_url, statement_timeout_ms=1000)
    session_factory = async_sessionmaker(eng, expire_on_commit=False, autoflush=False)
    try:
        async with session_factory() as session:
            with pytest.raises(DBAPIError):
                await session.execute(text("SELECT pg_sleep(2)"))
            # 必须能 rollback，避免连接卡在失败事务里
            await session.rollback()
            # 同一 Session 还能继续工作
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1
    finally:
        await eng.dispose()
