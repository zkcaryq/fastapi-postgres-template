"""真实 Alembic 完整生命周期测试。

本轮核心验证：

- 空 ``fastapi_template_test`` Schema
- ``revision --autogenerate`` 生成的 migration **内容非空且符合预期**
  （autogenerate 在无差异时会生成 pass/pass 空迁移而不报错，
  只断言“文件生成了”是假阳性，必须断言文件内容）
- ``upgrade head`` 真正在 PostgreSQL 上建表
- ``information_schema.columns`` 验证主键 ``is_identity = YES`` /
  ``identity_generation = BY DEFAULT``
- NOT NULL / UNIQUE / CHECK / FK 约束在系统目录里真实存在
- ``downgrade -1`` 真的把表删掉；``upgrade head`` 再次回来
- ``alembic check`` 报告无差异
- ``alembic_version`` 表落在 ``fastapi_template_test`` 而非 ``public``
- 增量流程：第一轮 3 张表 → 第二轮真实新增第 4 张表（阶段化 metadata）
- 生成的临时 revision 不落入仓库 ``alembic/versions/``

**不**改动 ``app/``、``alembic/``、``examples/`` 任何文件。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixture: 临时 alembic working dir + versions dir
# ---------------------------------------------------------------------------


@pytest.fixture
def alembic_workspace(tmp_path: Path) -> Iterator[Path]:
    """为本次 alembic 流程准备临时 ``versions`` 目录。

    ``script_location`` 用测试专用 ``tests/integration/_alembic``，
    但 ``version_locations`` 指向 ``tmp_path/versions``，这样生成的
    migration 文件不会落到仓库的 ``alembic/versions/``。
    """
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    yield tmp_path


def _make_config(workspace: Path) -> object:
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", "tests/integration/_alembic")
    cfg.set_main_option("version_locations", str(workspace / "versions"))
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option("sqlalchemy.url", "postgresql+psycopg://placeholder")
    # env.py exec 时会调 ``get_settings()``；清 cache 让它读到本用例的环境变量。
    from app.core import settings as settings_module

    settings_module.get_settings.cache_clear()
    return cfg


def _list_versions(workspace: Path) -> list[Path]:
    versions_dir = workspace / "versions"
    if not versions_dir.exists():
        return []
    return sorted(p for p in versions_dir.glob("*.py") if p.is_file())


# ---------------------------------------------------------------------------
# DDL 探针：直接读 information_schema / pg_catalog
# ---------------------------------------------------------------------------


def _column_info(engine: object, schema: str, table: str) -> list[dict[str, object]]:
    """读取指定表的全部列属性（包含 is_identity / identity_generation）。"""
    sql = text(
        """
        SELECT
            column_name,
            data_type,
            is_nullable,
            is_identity,
            identity_generation,
            column_default
        FROM information_schema.columns
        WHERE table_schema = :schema AND table_name = :table
        ORDER BY ordinal_position
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"schema": schema, "table": table}).mappings().all()
    return [dict(r) for r in rows]


def _tables_in_schema(engine: object, schema: str) -> set[str]:
    sql = text("SELECT tablename FROM pg_tables WHERE schemaname = :s")
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(sql, {"s": schema}).all()}


def _constraint_count(engine: object, schema: str, conname: str) -> int:
    sql = text(
        "SELECT COUNT(*) FROM pg_constraint "
        "WHERE conname = :c AND connamespace = "
        "(SELECT oid FROM pg_namespace WHERE nspname = :s)"
    )
    with engine.connect() as conn:
        return conn.execute(sql, {"c": conname, "s": schema}).scalar()


# ---------------------------------------------------------------------------
# 主测试：Alembic 完整生命周期
# ---------------------------------------------------------------------------


def test_alembic_full_lifecycle_on_real_postgres(
    integration_database_url: str,
    test_schema_name: str,
    clean_schema: None,
    alembic_workspace: Path,
) -> None:
    """完整流程：autogenerate → upgrade → check → DDL 验证 → downgrade → upgrade → check。"""
    from alembic import command
    from tests.integration import _models

    cfg = _make_config(alembic_workspace)

    # 1) autogenerate 第一份 migration
    command.revision(cfg, message="it: initial integration tables", autogenerate=True)
    rev_files = _list_versions(alembic_workspace)
    assert len(rev_files) == 1, f"应生成 1 份 revision，实际 {len(rev_files)}"
    rev_file = rev_files[0]
    # 文件名不能出现在 ``alembic/versions/``
    assert "alembic" not in rev_file.parts or "_alembic" in str(rev_file)

    # 1a) 反假阳性：migration 内容必须真的建表，且用 Identity 而非 SERIAL。
    # alembic 渲染为 ``sa.Identity(always=False)``，断言前缀即可。
    rev_src = rev_file.read_text(encoding="utf-8")
    for expected in (
        "integration_entity",
        "integration_parent",
        "integration_child",
        "integration_extra",
        "create_table",
        "sa.Identity(",
        f"schema='{test_schema_name}'",
    ):
        assert expected in rev_src, f"migration 缺少预期内容 {expected!r}"
    assert "nextval" not in rev_src, "主键不应使用 SERIAL/nextval"

    # 2) upgrade head
    command.upgrade(cfg, "head")

    # 3) alembic check
    command.check(cfg)

    # 4) 直接读 PostgreSQL 系统目录验证 DDL
    engine = create_engine(integration_database_url, isolation_level="AUTOCOMMIT")
    try:
        tables = _tables_in_schema(engine, test_schema_name)
        # 精确相等：4 张业务表 + alembic_version，不多不少（防脏对象）
        assert tables == {
            "integration_entity",
            "integration_parent",
            "integration_child",
            "integration_extra",
            "alembic_version",
        }, tables

        # alembic_version 必须出现在 fastapi_template_test。
        # public/test 里已有的 alembic_version 是历史遗留，本测试不读不写它们。
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT table_schema FROM information_schema.tables "
                    "WHERE table_name = 'alembic_version' "
                    "AND table_schema = :s"
                ),
                {"s": test_schema_name},
            ).all()
        assert len(row) == 1

        # IntegrationEntity 的列属性
        cols = _column_info(engine, test_schema_name, "integration_entity")
        cols_by_name = {c["column_name"]: c for c in cols}

        # 主键列 is_identity = YES, identity_generation = BY DEFAULT
        id_col = cols_by_name["id"]
        assert id_col["is_identity"] == "YES", id_col
        assert id_col["identity_generation"] == "BY DEFAULT", id_col
        assert id_col["data_type"] == "bigint", id_col

        # NOT NULL / 可空
        assert cols_by_name["name"]["is_nullable"] == "NO"
        assert cols_by_name["code"]["is_nullable"] == "NO"
        assert cols_by_name["optional_value"]["is_nullable"] == "YES"

        # 约束（名字由 Base 命名规则生成）
        assert _constraint_count(engine, test_schema_name, "uq_integration_entity_code") == 1
        assert (
            _constraint_count(engine, test_schema_name, "ck_integration_entity_ck_optional_value")
            == 1
        )
        with engine.connect() as conn:
            fk_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM pg_constraint "
                    "WHERE conname LIKE 'fk_%integration_child%' "
                    "AND connamespace = "
                    "(SELECT oid FROM pg_namespace WHERE nspname = :s)"
                ),
                {"s": test_schema_name},
            ).scalar()
        assert fk_count >= 1
    finally:
        engine.dispose()

    # 5) downgrade -1：唯一的 revision 被撤销，业务表必须消失
    command.downgrade(cfg, "-1")
    engine = create_engine(integration_database_url, isolation_level="AUTOCOMMIT")
    try:
        tables_after_down = _tables_in_schema(engine, test_schema_name)
        assert "integration_entity" not in tables_after_down
        assert "integration_parent" not in tables_after_down
        assert "integration_child" not in tables_after_down
        assert "integration_extra" not in tables_after_down
    finally:
        engine.dispose()

    # 6) upgrade head 再次回来
    command.upgrade(cfg, "head")
    engine = create_engine(integration_database_url, isolation_level="AUTOCOMMIT")
    try:
        tables_after_up = _tables_in_schema(engine, test_schema_name)
        assert "integration_entity" in tables_after_up
        assert "integration_extra" in tables_after_up
    finally:
        engine.dispose()

    # 7) 再 check
    command.check(cfg)
    assert _models.active_metadata() is _models.IntegrationBase.metadata


# ---------------------------------------------------------------------------
# 增量变更：第一轮 3 张表 → 第二轮真实新增第 4 张表
# ---------------------------------------------------------------------------


def _phase_metadata(schema: str, include_extra: bool) -> object:
    """构造阶段性 MetaData：复制指定表的副本，模拟“Model 逐步增加”。"""
    from sqlalchemy import MetaData

    from tests.integration._models import (
        NAMING_CONVENTION,
        IntegrationChild,
        IntegrationEntity,
        IntegrationExtra,
        IntegrationParent,
    )

    md = MetaData(schema=schema, naming_convention=NAMING_CONVENTION)
    for model in (IntegrationEntity, IntegrationParent, IntegrationChild):
        model.__table__.to_metadata(md)
    if include_extra:
        IntegrationExtra.__table__.to_metadata(md)
    return md


def test_alembic_increment_add_table(
    integration_database_url: str,
    test_schema_name: str,
    clean_schema: None,
    alembic_workspace: Path,
) -> None:
    """真实的增量迁移：第一轮 3 张表，第二轮 autogenerate 新增第 4 张。

    通过 ``_models.set_active_metadata()`` 控制 ``_alembic/env.py``
    在每次 exec 时看到的表集合；并对每份 migration 的**文件内容**做断言，
    防止“空迁移也算通过”的假阳性。
    """
    from alembic import command
    from tests.integration import _models

    cfg = _make_config(alembic_workspace)
    metadata_v1 = _phase_metadata(test_schema_name, include_extra=False)
    metadata_v2 = _phase_metadata(test_schema_name, include_extra=True)

    _models.set_active_metadata(metadata_v1)
    try:
        # --- 第一轮：只有 3 张表 ---
        command.revision(cfg, message="it: initial", autogenerate=True)
        rev1 = _list_versions(alembic_workspace)[0]
        src1 = rev1.read_text(encoding="utf-8")
        assert "integration_entity" in src1
        assert "integration_extra" not in src1, "第一轮不应包含 integration_extra"

        command.upgrade(cfg, "head")
        command.check(cfg)

        engine = create_engine(integration_database_url, isolation_level="AUTOCOMMIT")
        try:
            tables = _tables_in_schema(engine, test_schema_name)
            assert "integration_entity" in tables
            assert "integration_extra" not in tables, "第一轮 upgrade 后不应有 extra 表"
        finally:
            engine.dispose()

        # --- 第二轮：Model 集合新增 IntegrationExtra ---
        _models.set_active_metadata(metadata_v2)

        command.revision(cfg, message="it: add extra_table", autogenerate=True)
        rev_files = _list_versions(alembic_workspace)
        assert len(rev_files) == 2
        # 注意：不能用 ``rev_files[1]`` 定位第二份 migration——文件名以
        # **随机** revision hash 开头，字母序与创建顺序无关（曾导致 ~50% 假失败）。
        # alembic 文件名格式是 ``{hash}_{message_slug}.py``，slug 是确定的。
        rev2_candidates = list((alembic_workspace / "versions").glob("*it_add_extra_table.py"))
        assert len(rev2_candidates) == 1, rev2_candidates
        rev2 = rev2_candidates[0]
        src2 = rev2.read_text(encoding="utf-8")
        # 反假阳性核心断言：第二份 migration 必须真实包含 create_table，
        # 而不是 autogenerate 无差异时生成的 pass/pass 空壳。
        assert "create_table" in src2, f"第二份 migration 是空的：\n{src2}"
        assert "integration_extra" in src2

        command.upgrade(cfg, "head")
        command.check(cfg)

        engine = create_engine(integration_database_url, isolation_level="AUTOCOMMIT")
        try:
            tables = _tables_in_schema(engine, test_schema_name)
            assert "integration_extra" in tables
            cols = _column_info(engine, test_schema_name, "integration_extra")
            cols_by_name = {c["column_name"]: c for c in cols}
            assert cols_by_name["id"]["is_identity"] == "YES"
            assert cols_by_name["description"]["is_nullable"] == "NO"
        finally:
            engine.dispose()

        # --- 第二轮 downgrade：extra 表消失，其余保留 ---
        command.downgrade(cfg, "-1")
        engine = create_engine(integration_database_url, isolation_level="AUTOCOMMIT")
        try:
            tables = _tables_in_schema(engine, test_schema_name)
            assert "integration_extra" not in tables
            assert "integration_entity" in tables
        finally:
            engine.dispose()
    finally:
        _models.set_active_metadata(None)


# ---------------------------------------------------------------------------
# version_locations 是临时目录：结束后必须空
# ---------------------------------------------------------------------------


def test_versions_directory_does_not_pollute_repo(
    integration_database_url: str,
    clean_schema: None,
    alembic_workspace: Path,
) -> None:
    """生成的 revision 文件必须落在 ``tmp_path/versions``，不进 ``alembic/versions/``。"""
    from alembic import command

    cfg = _make_config(alembic_workspace)
    command.revision(cfg, message="it: pollution check", autogenerate=True)

    repo_alembic_versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    py_files = list(repo_alembic_versions.glob("*.py"))
    # 仓库 ``alembic/versions/`` 里只能有 ``.gitkeep``，没有 ``.py`` 文件。
    assert not py_files, f"alembic/versions/ 被污染：{py_files}"
