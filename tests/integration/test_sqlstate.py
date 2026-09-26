"""真实 PostgreSQL 上的 SQLSTATE 行为验证。

覆盖：
- 23505（UNIQUE）：重复插入触发并能被 Service 的 IntegrityError 映射捕获
- 23502（NOT NULL）：绕过 Pydantic 直接 ORM 写 NULL，验证数据库最后一道约束
- 23514（CHECK）：违反 CheckConstraint
- 23503（FK）：违反外键引用
- 23500 系列之外：正常路径
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, insert, text
from sqlalchemy.exc import IntegrityError

from tests.integration._models import (
    IntegrationChild,
    IntegrationEntity,
)

pytestmark = pytest.mark.integration


def _psycopg_sqlstate(exc: IntegrityError) -> str | None:
    """从 SQLAlchemy / psycopg 的异常里提取 SQLSTATE。"""
    orig = getattr(exc, "orig", None)
    if orig is None:
        return None
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


@pytest.fixture
def engine(integration_database_url: str, clean_schema: None):
    """为每次用例创建表，并提供同步 engine。"""
    from sqlalchemy import create_engine as _create_engine

    from tests.integration._models import IntegrationBase

    eng = _create_engine(integration_database_url, isolation_level="AUTOCOMMIT")
    try:
        # 直接 create_all 一次；不依赖 alembic 流程，独立验证 SQLSTATE。
        IntegrationBase.metadata.create_all(eng)
        yield eng
    finally:
        eng.dispose()


# ---------------------------------------------------------------------------
# 23505 UNIQUE
# ---------------------------------------------------------------------------


def test_unique_violation_returns_sqlstate_23505(engine):
    with engine.begin() as conn:
        conn.execute(insert(IntegrationEntity).values(name="Alice", code="ABC"))
    with engine.begin() as conn, pytest.raises(IntegrityError) as ei:
        conn.execute(insert(IntegrationEntity).values(name="Bob", code="ABC"))
    assert _psycopg_sqlstate(ei.value) == "23505", ei.value


# ---------------------------------------------------------------------------
# 23502 NOT NULL
# ---------------------------------------------------------------------------


def test_not_null_violation_returns_sqlstate_23502(engine):
    # 直接绕过 Schema 校验，把必填字段写 NULL
    with engine.begin() as conn, pytest.raises(IntegrityError) as ei:
        conn.execute(insert(IntegrationEntity).values(name=None, code="X1"))
    assert _psycopg_sqlstate(ei.value) == "23502", ei.value


# ---------------------------------------------------------------------------
# 23514 CHECK
# ---------------------------------------------------------------------------


def test_check_violation_returns_sqlstate_23514(engine):
    with engine.begin() as conn, pytest.raises(IntegrityError) as ei:
        conn.execute(
            insert(IntegrationEntity).values(
                name="Cathy", code="CH1", optional_value="forbidden_value"
            )
        )
    assert _psycopg_sqlstate(ei.value) == "23514", ei.value


# ---------------------------------------------------------------------------
# 23503 FK
# ---------------------------------------------------------------------------


def test_foreign_key_violation_returns_sqlstate_23503(engine):
    # 没插 parent，直接插 child → FK 违反
    with engine.begin() as conn, pytest.raises(IntegrityError) as ei:
        conn.execute(insert(IntegrationChild).values(parent_id=9999))
    assert _psycopg_sqlstate(ei.value) == "23503", ei.value


# ---------------------------------------------------------------------------
# 正常路径：所有约束都满足
# ---------------------------------------------------------------------------


def test_normal_insert_succeeds(engine):
    with engine.begin() as conn:
        conn.execute(
            insert(IntegrationEntity).values(name="Normal", code="NORMAL-1", optional_value="ok")
        )
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM fastapi_template_test.integration_entity")
        ).scalar()
    assert count == 1


def test_select_after_insert(engine):
    """SELECT 可读到 INSERT 的结果（前提是同一事务已 commit）。"""
    from sqlalchemy import select

    with engine.begin() as conn:
        conn.execute(insert(IntegrationEntity).values(name="Sel", code="SEL-1"))
    with engine.connect() as conn:
        rows = conn.execute(
            select(IntegrationEntity).where(IntegrationEntity.code == "SEL-1")
        ).all()
    assert len(rows) == 1
    assert rows[0].name == "Sel"


# ---------------------------------------------------------------------------
# search_path=pg_catalog 下的 ORM 行为
# ---------------------------------------------------------------------------


def test_orm_works_with_search_path_pinned_to_pg_catalog(
    integration_database_url: str, clean_schema: None
):
    """``search_path=pg_catalog`` 配合 MetaData.schema=fastapi_template_test。

    这是模板的核心组合：表不在默认 ``public``，也不在 ``$user``。
    必须由 MetaData 的 schema 限定 + search_path=pg_catalog 让 ORM 工作。
    """
    from sqlalchemy import select

    from app.core.settings import get_settings
    from tests.integration._models import IntegrationBase, IntegrationEntity

    settings = get_settings()
    engine = create_engine(
        integration_database_url,
        connect_args=settings.connect_args,
        isolation_level="AUTOCOMMIT",
    )
    try:
        # 确认连接上 search_path 真的是 pg_catalog
        with engine.connect() as conn:
            sp = conn.execute(text("SHOW search_path")).scalar()
        assert sp.split(",")[0].strip() == "pg_catalog"

        IntegrationBase.metadata.create_all(engine)
        try:
            with engine.begin() as conn:
                conn.execute(insert(IntegrationEntity).values(name="PgCat", code="PGCAT-1"))

            with engine.connect() as conn:
                rows = conn.execute(
                    select(IntegrationEntity).where(IntegrationEntity.code == "PGCAT-1")
                ).all()
            assert len(rows) == 1
            assert rows[0].name == "PgCat"
        finally:
            IntegrationBase.metadata.drop_all(engine)
    finally:
        engine.dispose()
