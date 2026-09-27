"""真实 PostgreSQL 上的 AsyncSession 行为验证。

覆盖：
- ``session.add()`` 不会自动 flush：同事务 SELECT 看不到新增行
- ``session.flush()`` 之后能看到，Identity 主键已就位
- ``session.commit()`` 之后普通属性不再触发隐式 IO（expire_on_commit=False）
- 事务 ``rollback()``：失败后所有改动消失
- 真 ``statement_timeout``：``pg_sleep(2)`` 在 1000ms 超时下被取消
"""
# ↑ 模块 docstring：验证异步 Session 的几个关键行为（autoflush、expire_on_commit、rollback、超时）。

# 这个 import 让类型标注用"未来注解"。
from __future__ import annotations

# 导入 pytest、SQLAlchemy 的 insert/select/text、异步引擎相关。
import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# 导入测试模型。
from tests.integration._models import IntegrationEntity

pytestmark = pytest.mark.integration
# ↑ 打 integration 标记。


def _make_async_engine(database_url: str, statement_timeout_ms: int | None = None):
    # ↑ 辅助函数：构造异步引擎，可覆盖 statement_timeout。

    """构造一个真实的 AsyncEngine；``statement_timeout`` 可调。"""
    # ↑ docstring。
    from app.core.settings import get_settings
    # ↑ 函数内导入。

    settings = get_settings()
    # ↑ 读配置。
    connect_args = dict(settings.connect_args)
    # ↑ 复制连接参数。
    if statement_timeout_ms is not None:
        # ↑ 如果传了超时值……
        # 覆盖默认 ``statement_timeout``，仅供本次测试。
        # ↑ 说明。
        new_options = []
        # ↑ 新 options 片段列表。
        for opt in connect_args["options"].split(" -c"):
            # ↑ 按 " -c" 拆分 options 字符串。
            if opt.startswith("statement_timeout="):
                # ↑ 找到 statement_timeout 片段。
                new_options.append(f"statement_timeout={statement_timeout_ms}")
                # ↑ 替换成新值。
            elif opt:
                # ↑ 其他非空片段。
                new_options.append(opt)
                # ↑ 保留。
        connect_args["options"] = " -c".join(new_options)
        # ↑ 重新拼回 options。

    return create_async_engine(database_url, connect_args=connect_args)
    # ↑ 用修改后的参数创建异步引擎。


@pytest.fixture
# ↑ fixture。
async def populated_db(integration_database_url, clean_schema):
    # ↑ 建表并写入一条记录，供各测试使用。

    """建表 + 写一条记录，关闭引擎后清理。"""
    # ↑ docstring。
    from tests.integration._models import IntegrationBase, IntegrationEntity
    # ↑ 函数内导入。

    eng = _make_async_engine(integration_database_url)
    # ↑ 创建异步引擎。
    session_factory = async_sessionmaker(eng, expire_on_commit=False, autoflush=False)
    # ↑ 创建会话工厂。
    try:
        # ↑ 尝试。
        async with eng.begin() as conn:
            # ↑ 开启事务连接。
            await conn.run_sync(IntegrationBase.metadata.create_all)
            # ↑ 用同步方式建表（run_sync 把同步函数跑在异步引擎上）。

        async with session_factory() as session:
            # ↑ 开会话。
            await session.execute(insert(IntegrationEntity).values(name="Initial", code="INIT-1"))
            # ↑ 插入一条初始记录。
            await session.commit()
            # ↑ 提交。

        yield eng, session_factory
        # ↑ 提供引擎和工厂。

        async with eng.begin() as conn:
            # ↑ 事务连接。
            await conn.run_sync(IntegrationBase.metadata.drop_all)
            # ↑ 删表。
    finally:
        # ↑ 最后。
        await eng.dispose()
        # ↑ 释放引擎。


# ---------------------------------------------------------------------------
# autoflush=False
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测 autoflush=False 的行为。


@pytest.mark.asyncio
# ↑ 异步测试。
async def test_session_add_does_not_flush_implicitly(integration_database_url, populated_db):
    # ↑ 测试：add() 后不自动 flush，同事务 SELECT 看不到新行。

    """``session.add()`` 之后同事务 SELECT 看不到新行（autoflush=False）。"""
    # ↑ docstring。
    _, session_factory = populated_db
    # ↑ 解包（丢弃引擎，只要工厂）。
    async with session_factory() as session:
        # ↑ 开会话。
        async with session.begin():
            # ↑ 开事务。
            new = IntegrationEntity(name="Buffered", code="BUF-1")
            # ↑ 新建对象。
            session.add(new)
            # ↑ 加入会话（尚未 flush，SQL 没发出去）。
            # 没 flush；同事务 SELECT 应看不到
            # ↑ 说明。
            count_before = (
                # ↑ 查询。
                await session.execute(
                    select(IntegrationEntity).where(IntegrationEntity.code == "BUF-1")
                    # ↑ 查 code=BUF-1。
                )
            ).all()
            # ↑ 取所有。
            assert count_before == []
            # ↑ 断言查不到（因为没 flush）。
        await session.rollback()
        # ↑ 回滚（清理）。


@pytest.mark.asyncio
# ↑ 异步测试。
async def test_session_flush_makes_row_visible_and_assigns_identity_pk(
    # ↑ 测试：flush 后行可见，且 Identity 主键被填充。
    integration_database_url,
    populated_db,
):
    """``flush()`` 之后行可见，且 Identity 主键已被数据库填充。"""
    # ↑ docstring。
    _, session_factory = populated_db
    # ↑ 解包。
    async with session_factory() as session:
        # ↑ 开会话。
        async with session.begin():
            # ↑ 开事务。
            new = IntegrationEntity(name="Flushed", code="FLU-1")
            # ↑ 新建对象。
            session.add(new)
            # ↑ 加入会话。
            # flush 之前主键是 None
            # ↑ 说明。
            assert new.id is None
            # ↑ 断言主键还没分配。
            await session.flush()
            # ↑ 手动 flush（真正发 SQL）。
            # flush 之后主键已被分配
            # ↑ 说明。
            assert new.id is not None
            # ↑ 断言主键已分配。
            assert new.id > 0
            # ↑ 断言主键大于 0。
            # 同事务 SELECT 可见
            # ↑ 说明。
            rows = (
                # ↑ 查询。
                await session.execute(
                    select(IntegrationEntity).where(IntegrationEntity.code == "FLU-1")
                    # ↑ 查 FLU-1。
                )
            ).all()
            # ↑ 取所有。
            assert len(rows) == 1
            # ↑ 断言查到一行。
        await session.rollback()
        # ↑ 回滚。


# ---------------------------------------------------------------------------
# expire_on_commit=False
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测 expire_on_commit=False 的行为。


@pytest.mark.asyncio
# ↑ 异步测试。
async def test_commit_does_not_trigger_implicit_io_on_loaded_attrs(
    # ↑ 测试：commit 后访问已加载属性不触发隐式 SQL。
    integration_database_url,
    populated_db,
):
    """commit 之后访问已加载属性不应触发隐式 SQL（expire_on_commit=False）。"""
    # ↑ docstring。
    _, session_factory = populated_db
    # ↑ 解包。
    async with session_factory() as session:
        # ↑ 开会话。
        async with session.begin():
            # ↑ 开事务。
            # 先查出来，构造已加载对象
            # ↑ 说明。
            stmt = select(IntegrationEntity).where(IntegrationEntity.code == "INIT-1")
            # ↑ 构造查询。
            entity = (await session.execute(stmt)).scalars().first()
            # ↑ 查出来。
            assert entity is not None
            # ↑ 断言存在。
            entity.name = "Renamed"
            # ↑ 修改属性。
        # commit 已发生；再读 ``entity.name`` 不应触发 SELECT
        # 如果触发，会被 SQLAlchemy 报错（async + 隐式 IO）。
        # 这是 expire_on_commit=False 的真实可验证效果。
        # ↑ 说明：因为 expire_on_commit=False，commit 后属性不会过期，
        #   再访问不会触发隐式查询（这在异步下会报错）。
        assert entity.name == "Renamed"
        # ↑ 断言属性值正确（如果触发了隐式 IO 会在这里报错）。


# ---------------------------------------------------------------------------
# transaction rollback
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测事务回滚。


@pytest.mark.asyncio
# ↑ 异步测试。
async def test_rollback_undoes_inserts(integration_database_url, populated_db):
    # ↑ 测试：事务回滚后，之前的插入全部消失。

    """事务内 INSERT A / INSERT B / 制造异常 / ROLLBACK → 全部消失。"""
    # ↑ docstring。
    _, session_factory = populated_db
    # ↑ 解包（工厂）。
    eng, _ = populated_db
    # ↑ 解包（引擎）。
    async with session_factory() as session:
        # ↑ 开会话。
        try:
            # ↑ 尝试。
            async with session.begin():
                # ↑ 开事务。
                await session.execute(insert(IntegrationEntity).values(name="A", code="ROLL-A"))
                # ↑ 插入 A。
                await session.execute(insert(IntegrationEntity).values(name="B", code="ROLL-B"))
                # ↑ 插入 B。
                # 故意触发异常
                # ↑ 说明。
                raise RuntimeError("boom")
                # ↑ 抛异常，触发回滚。
        except RuntimeError:
            # ↑ 捕获。
            await session.rollback()
            # ↑ 回滚。

    async with eng.connect() as conn:
        # ↑ 用引擎查询。
        a = (
            # ↑ 查 A。
            await conn.execute(select(IntegrationEntity).where(IntegrationEntity.code == "ROLL-A"))
        ).all()
        b = (
            # ↑ 查 B。
            await conn.execute(select(IntegrationEntity).where(IntegrationEntity.code == "ROLL-B"))
        ).all()
    assert a == []
    # ↑ 断言 A 不存在（回滚生效）。
    assert b == []
    # ↑ 断言 B 不存在。


@pytest.mark.asyncio
# ↑ 异步测试。
async def test_commit_persists(integration_database_url, populated_db):
    # ↑ 测试：commit 后数据真正落库。

    """``commit`` 之后数据真实落库。"""
    # ↑ docstring。
    eng, session_factory = populated_db
    # ↑ 解包引擎和工厂。
    async with session_factory() as session, session.begin():
        # ↑ 开会话和事务。
        await session.execute(insert(IntegrationEntity).values(name="Committed", code="COM-1"))
        # ↑ 插入（事务结束自动 commit）。

    async with eng.connect() as conn:
        # ↑ 查询。
        rows = (
            # ↑ 查。
            await conn.execute(select(IntegrationEntity).where(IntegrationEntity.code == "COM-1"))
        ).all()
        # ↑ 取所有。
    assert len(rows) == 1
    # ↑ 断言查到一行（commit 生效）。


# ---------------------------------------------------------------------------
# statement_timeout 真的会让 pg_sleep 被取消
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测语句超时。


@pytest.mark.asyncio
# ↑ 异步测试。
async def test_statement_timeout_cancels_pg_sleep(integration_database_url, populated_db):
    # ↑ 测试：statement_timeout=1000ms 下，pg_sleep(2) 被 PG 主动取消。

    """在 ``statement_timeout=1000ms`` 下 ``pg_sleep(2)`` 必须被 PG 主动取消。"""
    # ↑ docstring。
    from sqlalchemy.exc import DBAPIError
    # ↑ 函数内导入。

    # 1000ms 超时；调用 pg_sleep(2) 会触发 ``canceling statement due to statement timeout``
    # ↑ 说明。
    eng = _make_async_engine(integration_database_url, statement_timeout_ms=1000)
    # ↑ 用 1000ms 超时创建引擎。
    try:
        # ↑ 尝试。
        async with eng.connect() as conn:
            # ↑ 连接。
            with pytest.raises(DBAPIError) as exc:
                # ↑ 断言抛 DBAPIError。
                await conn.execute(text("SELECT pg_sleep(2)"))
                # ↑ 执行会睡 2 秒的语句（超过 1 秒超时，被取消）。
        # 错误信息里应有超时关键字
        # ↑ 说明。
        msg = str(exc.value).lower()
        # ↑ 取异常信息。
        assert "cancel" in msg or "timeout" in msg, msg
        # ↑ 断言含超时/取消关键词。
    finally:
        # ↑ 最后。
        await eng.dispose()
        # ↑ 释放引擎。


@pytest.mark.asyncio
# ↑ 异步测试。
async def test_session_rollback_after_statement_timeout(integration_database_url, populated_db):
    # ↑ 测试：语句超时后 Session 能 rollback 恢复。

    """statement timeout 后 Session 必须能 rollback 回到可用状态。"""
    # ↑ docstring。
    from sqlalchemy.exc import DBAPIError
    # ↑ 函数内导入。

    eng = _make_async_engine(integration_database_url, statement_timeout_ms=1000)
    # ↑ 用 1000ms 超时创建引擎。
    session_factory = async_sessionmaker(eng, expire_on_commit=False, autoflush=False)
    # ↑ 创建会话工厂。
    try:
        # ↑ 尝试。
        async with session_factory() as session:
            # ↑ 开会话。
            with pytest.raises(DBAPIError):
                # ↑ 断言抛 DBAPIError。
                await session.execute(text("SELECT pg_sleep(2)"))
                # ↑ 执行超时语句。
            # 必须能 rollback，避免连接卡在失败事务里
            # ↑ 说明。
            await session.rollback()
            # ↑ 回滚。
            # 同一 Session 还能继续工作
            # ↑ 说明。
            result = await session.execute(text("SELECT 1"))
            # ↑ 再执行正常语句。
            assert result.scalar() == 1
            # ↑ 断言能正常工作。
    finally:
        # ↑ 最后。
        await eng.dispose()
        # ↑ 释放引擎。
