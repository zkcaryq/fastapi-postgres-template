"""真实 PostgreSQL 上的 SQLSTATE 行为验证。

覆盖：
- 23505（UNIQUE）：重复插入触发并能被 Service 的 IntegrityError 映射捕获
- 23502（NOT NULL）：绕过 Pydantic 直接 ORM 写 NULL，验证数据库最后一道约束
- 23514（CHECK）：违反 CheckConstraint
- 23503（FK）：违反外键引用
- 23500 系列之外：正常路径
"""
# ↑ 模块 docstring：测试数据库约束违反时返回的标准错误码（SQLSTATE）。
#   这些码是数据库的"稳定错误码"，阶段 7 的 Service 层就靠它们做错误映射。

# 这个 import 让类型标注用"未来注解"。
from __future__ import annotations

# 导入 pytest、SQLAlchemy 的引擎/insert/text、IntegrityError。
import pytest
from sqlalchemy import create_engine, insert, text
from sqlalchemy.exc import IntegrityError

# 导入测试模型（子表、主表）。
from tests.integration._models import (
    IntegrationChild,
    IntegrationEntity,
)

pytestmark = pytest.mark.integration
# ↑ 给本文件所有测试打上 integration 标记（默认跳过，需 -m integration 才跑）。


def _psycopg_sqlstate(exc: IntegrityError) -> str | None:
    # ↑ 辅助函数：从异常里提取 SQLSTATE 错误码。

    """从 SQLAlchemy / psycopg 的异常里提取 SQLSTATE。"""
    # ↑ docstring。
    orig = getattr(exc, "orig", None)
    # ↑ 取出底层驱动抛的原始异常。
    if orig is None:
        # ↑ 如果没有原始异常……
        return None
        # ↑ 返回 None。
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    # ↑ 优先取 sqlstate，取不到再取 pgcode。


@pytest.fixture
# ↑ fixture。
def engine(integration_database_url: str, clean_schema: None):
    # ↑ 为每个用例建表并提供同步引擎。

    """为每次用例创建表，并提供同步 engine。"""
    # ↑ docstring。
    from sqlalchemy import create_engine as _create_engine

    # ↑ 函数内导入（取别名避免和文件顶部的 create_engine 冲突）。
    from tests.integration._models import IntegrationBase
    # ↑ 导入测试基类。

    eng = _create_engine(integration_database_url, isolation_level="AUTOCOMMIT")
    # ↑ 创建同步引擎。
    try:
        # ↑ 尝试。
        # 直接 create_all 一次；不依赖 alembic 流程，独立验证 SQLSTATE。
        # ↑ 说明：这里直接用 create_all 建表，不走 Alembic。
        IntegrationBase.metadata.create_all(eng)
        # ↑ 建所有测试表。
        yield eng
        # ↑ 提供引擎。
    finally:
        # ↑ 最后。
        eng.dispose()
        # ↑ 释放引擎。


# ---------------------------------------------------------------------------
# 23505 UNIQUE
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测唯一约束冲突。


def test_unique_violation_returns_sqlstate_23505(engine):
    # ↑ 测试：重复插入触发 23505（唯一约束）。

    with engine.begin() as conn:
        # ↑ 开启事务。
        conn.execute(insert(IntegrationEntity).values(name="Alice", code="ABC"))
        # ↑ 插入 code=ABC。
    with engine.begin() as conn, pytest.raises(IntegrityError) as ei:
        # ↑ 再开事务，并断言会抛 IntegrityError。
        conn.execute(insert(IntegrationEntity).values(name="Bob", code="ABC"))
        # ↑ 再次插入相同 code=ABC（违反唯一约束）。
    assert _psycopg_sqlstate(ei.value) == "23505", ei.value
    # ↑ 断言错误码是 23505。


# ---------------------------------------------------------------------------
# 23502 NOT NULL
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测 NOT NULL 约束。


def test_not_null_violation_returns_sqlstate_23502(engine):
    # ↑ 测试：给必填字段写 NULL 触发 23502。

    # 直接绕过 Schema 校验，把必填字段写 NULL
    # ↑ 说明：这里直接写库，绕过 Pydantic 校验，验证数据库最后一道约束。
    with engine.begin() as conn, pytest.raises(IntegrityError) as ei:
        # ↑ 断言抛 IntegrityError。
        conn.execute(insert(IntegrationEntity).values(name=None, code="X1"))
        # ↑ 给必填的 name 写 NULL。
    assert _psycopg_sqlstate(ei.value) == "23502", ei.value
    # ↑ 断言错误码 23502。


# ---------------------------------------------------------------------------
# 23514 CHECK
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测检查约束。


def test_check_violation_returns_sqlstate_23514(engine):
    # ↑ 测试：违反 CheckConstraint 触发 23514。

    with engine.begin() as conn, pytest.raises(IntegrityError) as ei:
        # ↑ 断言抛 IntegrityError。
        conn.execute(
            # ↑ 插入。
            insert(IntegrationEntity).values(
                name="Cathy",
                code="CH1",
                optional_value="forbidden_value",
                # ↑ optional_value 用被禁止的值，触发检查约束。
            )
        )
    assert _psycopg_sqlstate(ei.value) == "23514", ei.value
    # ↑ 断言错误码 23514。


# ---------------------------------------------------------------------------
# 23503 FK
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测外键约束。


def test_foreign_key_violation_returns_sqlstate_23503(engine):
    # ↑ 测试：违反外键引用触发 23503。

    # 没插 parent，直接插 child → FK 违反
    # ↑ 说明。
    with engine.begin() as conn, pytest.raises(IntegrityError) as ei:
        # ↑ 断言抛 IntegrityError。
        conn.execute(insert(IntegrationChild).values(parent_id=9999))
        # ↑ 插入一个不存在的 parent_id，违反外键。
    assert _psycopg_sqlstate(ei.value) == "23503", ei.value
    # ↑ 断言错误码 23503。


# ---------------------------------------------------------------------------
# 正常路径：所有约束都满足
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测正常路径。


def test_normal_insert_succeeds(engine):
    # ↑ 测试：满足所有约束时正常插入成功。

    with engine.begin() as conn:
        # ↑ 开启事务。
        conn.execute(
            # ↑ 插入。
            insert(IntegrationEntity).values(name="Normal", code="NORMAL-1", optional_value="ok")
            # ↑ 合法数据。
        )
    with engine.connect() as conn:
        # ↑ 连接查询。
        count = conn.execute(
            # ↑ 查询数量。
            text("SELECT COUNT(*) FROM fastapi_template_test.integration_entity")
            # ↑ 用完整 Schema 限定名查。
        ).scalar()
        # ↑ 取单个值。
    assert count == 1
    # ↑ 断言有一行。


def test_select_after_insert(engine):
    # ↑ 测试：插入后能查出来。

    """SELECT 可读到 INSERT 的结果（前提是同一事务已 commit）。"""
    # ↑ docstring。
    from sqlalchemy import select
    # ↑ 函数内导入 select。

    with engine.begin() as conn:
        # ↑ 事务内插入。
        conn.execute(insert(IntegrationEntity).values(name="Sel", code="SEL-1"))
        # ↑ 插入。
    with engine.connect() as conn:
        # ↑ 连接查询。
        rows = conn.execute(
            # ↑ 查询。
            select(IntegrationEntity).where(IntegrationEntity.code == "SEL-1")
            # ↑ 查 code=SEL-1 的行。
        ).all()
        # ↑ 取所有行。
    assert len(rows) == 1
    # ↑ 断言一行。
    assert rows[0].name == "Sel"
    # ↑ 断言名字正确。


# ---------------------------------------------------------------------------
# search_path=pg_catalog 下的 ORM 行为
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测 search_path=pg_catalog 时 ORM 还能正常工作。


def test_orm_works_with_search_path_pinned_to_pg_catalog(
    # ↑ 测试：search_path 固定为 pg_catalog 时，ORM 配合 schema 限定仍能工作。
    integration_database_url: str,
    clean_schema: None,
):
    """``search_path=pg_catalog`` 配合 MetaData.schema=fastapi_template_test。

    这是模板的核心组合：表不在默认 ``public``，也不在 ``$user``。
    必须由 MetaData 的 schema 限定 + search_path=pg_catalog 让 ORM 工作。
    """
    # ↑ docstring：解释这是模板的核心设定。
    from sqlalchemy import select

    # ↑ 函数内导入 select。
    from app.core.settings import get_settings
    from tests.integration._models import IntegrationBase, IntegrationEntity
    # ↑ 导入配置和测试模型。

    settings = get_settings()
    # ↑ 读取配置。
    engine = create_engine(
        # ↑ 创建引擎。
        integration_database_url,
        # ↑ URL。
        connect_args=settings.connect_args,
        # ↑ 用生产同款连接参数（含 search_path=pg_catalog）。
        isolation_level="AUTOCOMMIT",
        # ↑ 自动提交模式。
    )
    try:
        # ↑ 尝试。
        # 确认连接上 search_path 真的是 pg_catalog
        # ↑ 说明。
        with engine.connect() as conn:
            # ↑ 连接。
            sp = conn.execute(text("SHOW search_path")).scalar()
            # ↑ 查询 search_path。
        assert sp.split(",")[0].strip() == "pg_catalog"
        # ↑ 断言第一项是 pg_catalog。

        IntegrationBase.metadata.create_all(engine)
        # ↑ 建表。
        try:
            # ↑ 尝试。
            with engine.begin() as conn:
                # ↑ 事务内插入。
                conn.execute(insert(IntegrationEntity).values(name="PgCat", code="PGCAT-1"))
                # ↑ 插入。

            with engine.connect() as conn:
                # ↑ 查询。
                rows = conn.execute(
                    # ↑ 查询。
                    select(IntegrationEntity).where(IntegrationEntity.code == "PGCAT-1")
                    # ↑ 查 PGCAT-1。
                ).all()
                # ↑ 取所有。
            assert len(rows) == 1
            # ↑ 断言一行。
            assert rows[0].name == "PgCat"
            # ↑ 断言名字。
        finally:
            # ↑ 内层清理。
            IntegrationBase.metadata.drop_all(engine)
            # ↑ 删表。
    finally:
        # ↑ 外层清理。
        engine.dispose()
        # ↑ 释放引擎。
