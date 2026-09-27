"""真实 Alembic 完整生命周期测试。

本轮核心验证：

- 空 ``fastapi_template_test`` Schema
- ``revision --autogenerate`` 生成的 migration **内容非空且符合预期**
  （autogenerate 在无差异时会生成 pass/pass 空迁移而不报错，
  只断言"文件生成了"是假阳性，必须断言文件内容）
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
# ↑ 模块 docstring：这是集成测试里最核心的一个——完整验证 Alembic 的
#   整个生命周期（生成→升级→检查→降级→再升级），并且是阶段 3 教学内容的"真实验证"。

# 这个 import 让类型标注用"未来注解"。
from __future__ import annotations

# 导入 Iterator 和 Path。
from collections.abc import Iterator
from pathlib import Path

# 导入 pytest、SQLAlchemy 的引擎/text。
import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration
# ↑ 打 integration 标记。


# ---------------------------------------------------------------------------
# Fixture: 临时 alembic working dir + versions dir
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面准备临时的迁移工作目录。


@pytest.fixture
# ↑ fixture。
def alembic_workspace(tmp_path: Path) -> Iterator[Path]:
    # ↑ 提供一个临时工作目录，迁移文件会生成在这里（不进仓库）。

    """为本次 alembic 流程准备临时 ``versions`` 目录。

    ``script_location`` 用测试专用 ``tests/integration/_alembic``，
    但 ``version_locations`` 指向 ``tmp_path/versions``，这样生成的
    migration 文件不会落到仓库的 ``alembic/versions/``。
    """
    # ↑ docstring。
    versions_dir = tmp_path / "versions"
    # ↑ 在临时目录下建一个 versions 子目录。
    versions_dir.mkdir()
    # ↑ 创建它。
    yield tmp_path
    # ↑ 提供临时目录。


def _make_config(workspace: Path) -> object:
    # ↑ 辅助函数：构造 Alembic 配置对象。

    from alembic.config import Config
    # ↑ 函数内导入。

    cfg = Config()
    # ↑ 创建配置对象。
    cfg.set_main_option("script_location", "tests/integration/_alembic")
    # ↑ 指定脚本位置（用测试专用的 alembic 目录）。
    cfg.set_main_option("version_locations", str(workspace / "versions"))
    # ↑ 指定迁移文件生成位置（临时目录，不进仓库）。
    cfg.set_main_option("path_separator", "os")
    # ↑ 路径分隔符用系统默认。
    cfg.set_main_option("sqlalchemy.url", "postgresql+psycopg://placeholder")
    # ↑ 占位 URL（实际 URL 由 env.py 里的 get_settings 提供）。
    # env.py exec 时会调 ``get_settings()``；清 cache 让它读到本用例的环境变量。
    # ↑ 说明。
    from app.core import settings as settings_module
    # ↑ 函数内导入。

    settings_module.get_settings.cache_clear()
    # ↑ 清配置缓存。
    return cfg
    # ↑ 返回配置。


def _list_versions(workspace: Path) -> list[Path]:
    # ↑ 辅助函数：列出临时目录里生成的迁移文件。

    versions_dir = workspace / "versions"
    # ↑ versions 目录。
    if not versions_dir.exists():
        # ↑ 如果不存在……
        return []
        # ↑ 返回空列表。
    return sorted(p for p in versions_dir.glob("*.py") if p.is_file())
    # ↑ 列出所有 .py 文件并排序。


# ---------------------------------------------------------------------------
# DDL 探针：直接读 information_schema / pg_catalog
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面几个辅助函数直接查数据库系统目录验证 DDL。


def _column_info(engine: object, schema: str, table: str) -> list[dict[str, object]]:
    # ↑ 辅助函数：读取指定表的所有列属性。

    """读取指定表的全部列属性（包含 is_identity / identity_generation）。"""
    # ↑ docstring。
    sql = text(
        # ↑ 原生 SQL。
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
        # ↑ 查询某 Schema 下某张表的所有列信息，按列顺序排序。
    )
    with engine.connect() as conn:
        # ↑ 连接。
        rows = conn.execute(sql, {"schema": schema, "table": table}).mappings().all()
        # ↑ 执行查询，mappings() 让每行是字典，all() 取全部。
    return [dict(r) for r in rows]
    # ↑ 转成字典列表返回。


def _tables_in_schema(engine: object, schema: str) -> set[str]:
    # ↑ 辅助函数：列出某 Schema 下的所有表名。

    sql = text("SELECT tablename FROM pg_tables WHERE schemaname = :s")
    # ↑ 查询表名。
    with engine.connect() as conn:
        # ↑ 连接。
        return {r[0] for r in conn.execute(sql, {"s": schema}).all()}
        # ↑ 返回表名集合。


def _constraint_count(engine: object, schema: str, conname: str) -> int:
    # ↑ 辅助函数：统计某个约束名的数量。

    sql = text(
        # ↑ 原生 SQL。
        "SELECT COUNT(*) FROM pg_constraint "
        "WHERE conname = :c AND connamespace = "
        "(SELECT oid FROM pg_namespace WHERE nspname = :s)"
        # ↑ 在指定 Schema 下查指定约束名的数量。
    )
    with engine.connect() as conn:
        # ↑ 连接。
        return conn.execute(sql, {"c": conname, "s": schema}).scalar()
        # ↑ 返回数量。


# ---------------------------------------------------------------------------
# 主测试：Alembic 完整生命周期
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面是主测试。


def test_alembic_full_lifecycle_on_real_postgres(
    # ↑ 主测试：完整走一遍 Alembic 生命周期。
    integration_database_url: str,
    # ↑ 数据库 URL。
    test_schema_name: str,
    # ↑ 测试 Schema 名。
    clean_schema: None,
    # ↑ 清理 fixture。
    alembic_workspace: Path,
    # ↑ 临时工作目录。
) -> None:
    # ↑ 返回 None。

    """完整流程：autogenerate → upgrade → check → DDL 验证 → downgrade → upgrade → check。"""
    # ↑ docstring。
    from alembic import command
    from tests.integration import _models
    # ↑ 函数内导入 alembic 命令和测试模型。

    cfg = _make_config(alembic_workspace)
    # ↑ 构造配置。

    # 1) autogenerate 第一份 migration
    # ↑ 步骤 1。
    command.revision(cfg, message="it: initial integration tables", autogenerate=True)
    # ↑ 自动生成迁移。
    rev_files = _list_versions(alembic_workspace)
    # ↑ 列出生成的迁移文件。
    assert len(rev_files) == 1, f"应生成 1 份 revision，实际 {len(rev_files)}"
    # ↑ 断言只生成了 1 份。
    rev_file = rev_files[0]
    # ↑ 取出那份。
    # 文件名不能出现在 ``alembic/versions/``
    # ↑ 说明。
    assert "alembic" not in rev_file.parts or "_alembic" in str(rev_file)
    # ↑ 断言文件不在仓库的 alembic/versions/ 里。

    # 1a) 反假阳性：migration 内容必须真的建表，且用 Identity 而非 SERIAL。
    # alembic 渲染为 ``sa.Identity(always=False)``，断言前缀即可。
    # ↑ 说明：关键——不能只断言"文件生成了"，要断言文件内容真的建表了。
    rev_src = rev_file.read_text(encoding="utf-8")
    # ↑ 读取迁移文件内容。
    for expected in (
        # ↑ 遍历要检查的内容。
        "integration_entity",
        "integration_parent",
        "integration_child",
        "integration_extra",
        "create_table",
        "sa.Identity(",
        f"schema='{test_schema_name}'",
        # ↑ 这四张表、create_table、sa.Identity、schema 限定都应该出现。
    ):
        assert expected in rev_src, f"migration 缺少预期内容 {expected!r}"
        # ↑ 逐项断言。
    assert "nextval" not in rev_src, "主键不应使用 SERIAL/nextval"
    # ↑ 断言没有 SERIAL 的 nextval。

    # 2) upgrade head
    # ↑ 步骤 2。
    command.upgrade(cfg, "head")
    # ↑ 升级到最新。

    # 3) alembic check
    # ↑ 步骤 3。
    command.check(cfg)
    # ↑ 检查无差异。

    # 4) 直接读 PostgreSQL 系统目录验证 DDL
    # ↑ 步骤 4。
    engine = create_engine(integration_database_url, isolation_level="AUTOCOMMIT")
    # ↑ 创建引擎。
    try:
        # ↑ 尝试。
        tables = _tables_in_schema(engine, test_schema_name)
        # ↑ 列出表。
        # 精确相等：4 张业务表 + alembic_version，不多不少（防脏对象）
        # ↑ 说明。
        assert tables == {
            # ↑ 断言表集合精确相等。
            "integration_entity",
            "integration_parent",
            "integration_child",
            "integration_extra",
            "alembic_version",
        }, tables
        # ↑ 断言是这 5 张表（失败时打印 tables）。

        # alembic_version 必须出现在 fastapi_template_test。
        # public/test 里已有的 alembic_version 是历史遗留，本测试不读不写它们。
        # ↑ 说明。
        with engine.connect() as conn:
            # ↑ 连接。
            row = conn.execute(
                # ↑ 查询。
                text(
                    "SELECT table_schema FROM information_schema.tables "
                    "WHERE table_name = 'alembic_version' "
                    "AND table_schema = :s"
                ),
                # ↑ 查测试 Schema 下是否有 alembic_version。
                {"s": test_schema_name},
                # ↑ 参数。
            ).all()
            # ↑ 取所有。
        assert len(row) == 1
        # ↑ 断言存在（在测试 Schema 里）。

        # IntegrationEntity 的列属性
        # ↑ 说明。
        cols = _column_info(engine, test_schema_name, "integration_entity")
        # ↑ 读列信息。
        cols_by_name = {c["column_name"]: c for c in cols}
        # ↑ 按列名建立索引。

        # 主键列 is_identity = YES, identity_generation = BY DEFAULT
        # ↑ 说明。
        id_col = cols_by_name["id"]
        # ↑ 取主键列。
        assert id_col["is_identity"] == "YES", id_col
        # ↑ 断言是 identity。
        assert id_col["identity_generation"] == "BY DEFAULT", id_col
        # ↑ 断言生成方式 BY DEFAULT。
        assert id_col["data_type"] == "bigint", id_col
        # ↑ 断言类型 bigint。

        # NOT NULL / 可空
        # ↑ 说明。
        assert cols_by_name["name"]["is_nullable"] == "NO"
        # ↑ 断言 name 不可空。
        assert cols_by_name["code"]["is_nullable"] == "NO"
        # ↑ 断言 code 不可空。
        assert cols_by_name["optional_value"]["is_nullable"] == "YES"
        # ↑ 断言 optional_value 可空。

        # 约束（名字由 Base 命名规则生成）
        # ↑ 说明。
        assert _constraint_count(engine, test_schema_name, "uq_integration_entity_code") == 1
        # ↑ 断言唯一约束存在。
        assert (
            _constraint_count(engine, test_schema_name, "ck_integration_entity_ck_optional_value")
            == 1
        )
        # ↑ 断言检查约束存在。
        with engine.connect() as conn:
            # ↑ 连接。
            fk_count = conn.execute(
                # ↑ 查询外键数量。
                text(
                    "SELECT COUNT(*) FROM pg_constraint "
                    "WHERE conname LIKE 'fk_%integration_child%' "
                    "AND connamespace = "
                    "(SELECT oid FROM pg_namespace WHERE nspname = :s)"
                ),
                # ↑ 查 integration_child 相关的外键。
                {"s": test_schema_name},
                # ↑ 参数。
            ).scalar()
            # ↑ 取单个值。
        assert fk_count >= 1
        # ↑ 断言至少一个外键。
    finally:
        # ↑ 最后。
        engine.dispose()
        # ↑ 释放引擎。

    # 5) downgrade -1：唯一的 revision 被撤销，业务表必须消失
    # ↑ 步骤 5。
    command.downgrade(cfg, "-1")
    # ↑ 降级一步。
    engine = create_engine(integration_database_url, isolation_level="AUTOCOMMIT")
    # ↑ 重新建引擎。
    try:
        # ↑ 尝试。
        tables_after_down = _tables_in_schema(engine, test_schema_name)
        # ↑ 列出降级后的表。
        assert "integration_entity" not in tables_after_down
        # ↑ 断言主表没了。
        assert "integration_parent" not in tables_after_down
        # ↑ 断言父表没了。
        assert "integration_child" not in tables_after_down
        # ↑ 断言子表没了。
        assert "integration_extra" not in tables_after_down
        # ↑ 断言额外表没了。
    finally:
        # ↑ 最后。
        engine.dispose()
        # ↑ 释放引擎。

    # 6) upgrade head 再次回来
    # ↑ 步骤 6。
    command.upgrade(cfg, "head")
    # ↑ 再升级。
    engine = create_engine(integration_database_url, isolation_level="AUTOCOMMIT")
    # ↑ 建引擎。
    try:
        # ↑ 尝试。
        tables_after_up = _tables_in_schema(engine, test_schema_name)
        # ↑ 列出表。
        assert "integration_entity" in tables_after_up
        # ↑ 断言主表回来了。
        assert "integration_extra" in tables_after_up
        # ↑ 断言额外表回来了。
    finally:
        # ↑ 最后。
        engine.dispose()
        # ↑ 释放引擎。

    # 7) 再 check
    # ↑ 步骤 7。
    command.check(cfg)
    # ↑ 再检查。
    assert _models.active_metadata() is _models.IntegrationBase.metadata
    # ↑ 断言 active_metadata 恢复为默认完整值。


# ---------------------------------------------------------------------------
# 增量变更：第一轮 3 张表 → 第二轮真实新增第 4 张表
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测增量迁移。


def _phase_metadata(schema: str, include_extra: bool) -> object:
    # ↑ 辅助函数：构造"阶段性"的表集合（模拟 Model 逐步增加）。

    """构造阶段性 MetaData：复制指定表的副本，模拟"Model 逐步增加"。"""
    # ↑ docstring。
    from sqlalchemy import MetaData

    # ↑ 函数内导入。
    from tests.integration._models import (
        NAMING_CONVENTION,
        IntegrationChild,
        IntegrationEntity,
        IntegrationExtra,
        IntegrationParent,
    )
    # ↑ 导入测试模型和命名约定。

    md = MetaData(schema=schema, naming_convention=NAMING_CONVENTION)
    # ↑ 新建一个 MetaData。
    for model in (IntegrationEntity, IntegrationParent, IntegrationChild):
        # ↑ 遍历前三张表的模型。
        model.__table__.to_metadata(md)
        # ↑ 把表复制到这个新 MetaData 里。
    if include_extra:
        # ↑ 如果需要包含额外表……
        IntegrationExtra.__table__.to_metadata(md)
        # ↑ 也加进去。
    return md
    # ↑ 返回。


def test_alembic_increment_add_table(
    # ↑ 测试：真实的增量迁移（第一轮 3 表，第二轮加第 4 表）。
    integration_database_url: str,
    test_schema_name: str,
    clean_schema: None,
    alembic_workspace: Path,
) -> None:
    """真实的增量迁移：第一轮 3 张表，第二轮 autogenerate 新增第 4 张。

    通过 ``_models.set_active_metadata()`` 控制 ``_alembic/env.py``
    在每次 exec 时看到的表集合；并对每份 migration 的**文件内容**做断言，
    防止"空迁移也算通过"的假阳性。
    """
    # ↑ docstring。
    from alembic import command
    from tests.integration import _models
    # ↑ 函数内导入。

    cfg = _make_config(alembic_workspace)
    # ↑ 构造配置。
    metadata_v1 = _phase_metadata(test_schema_name, include_extra=False)
    # ↑ 第一阶段：3 张表（不含 extra）。
    metadata_v2 = _phase_metadata(test_schema_name, include_extra=True)
    # ↑ 第二阶段：4 张表（含 extra）。

    _models.set_active_metadata(metadata_v1)
    # ↑ 先让 Alembic 只看到 3 张表。
    try:
        # ↑ 尝试。
        # --- 第一轮：只有 3 张表 ---
        # ↑ 说明。
        command.revision(cfg, message="it: initial", autogenerate=True)
        # ↑ 生成第一份迁移。
        rev1 = _list_versions(alembic_workspace)[0]
        # ↑ 取第一份。
        src1 = rev1.read_text(encoding="utf-8")
        # ↑ 读内容。
        assert "integration_entity" in src1
        # ↑ 断言包含主表。
        assert "integration_extra" not in src1, "第一轮不应包含 integration_extra"
        # ↑ 断言不包含 extra（第一轮还没它）。

        command.upgrade(cfg, "head")
        # ↑ 升级。
        command.check(cfg)
        # ↑ 检查。

        engine = create_engine(integration_database_url, isolation_level="AUTOCOMMIT")
        # ↑ 建引擎。
        try:
            # ↑ 尝试。
            tables = _tables_in_schema(engine, test_schema_name)
            # ↑ 列出表。
            assert "integration_entity" in tables
            # ↑ 断言主表在。
            assert "integration_extra" not in tables, "第一轮 upgrade 后不应有 extra 表"
            # ↑ 断言 extra 不在。
        finally:
            # ↑ 最后。
            engine.dispose()
            # ↑ 释放引擎。

        # --- 第二轮：Model 集合新增 IntegrationExtra ---
        # ↑ 说明。
        _models.set_active_metadata(metadata_v2)
        # ↑ 切换为 4 张表。

        command.revision(cfg, message="it: add extra_table", autogenerate=True)
        # ↑ 生成第二份迁移。
        rev_files = _list_versions(alembic_workspace)
        # ↑ 列出迁移文件。
        assert len(rev_files) == 2
        # ↑ 断言现在是 2 份。
        # 注意：不能用 ``rev_files[1]`` 定位第二份 migration——文件名以
        # **随机** revision hash 开头，字母序与创建顺序无关（曾导致 ~50% 假失败）。
        # alembic 文件名格式是 ``{hash}_{message_slug}.py``，slug 是确定的。
        # ↑ 说明：迁移文件名带随机 hash，不能按文件名排序找第二份。
        rev2_candidates = list((alembic_workspace / "versions").glob("*it_add_extra_table.py"))
        # ↑ 用确定的 message slug 找到第二份迁移。
        assert len(rev2_candidates) == 1, rev2_candidates
        # ↑ 断言只有一份匹配。
        rev2 = rev2_candidates[0]
        # ↑ 取出。
        src2 = rev2.read_text(encoding="utf-8")
        # ↑ 读内容。
        # 反假阳性核心断言：第二份 migration 必须真实包含 create_table，
        # 而不是 autogenerate 无差异时生成的 pass/pass 空壳。
        # ↑ 说明。
        assert "create_table" in src2, f"第二份 migration 是空的：\n{src2}"
        # ↑ 断言第二份真的建表了（不是空迁移）。
        assert "integration_extra" in src2
        # ↑ 断言包含 extra 表。

        command.upgrade(cfg, "head")
        # ↑ 升级。
        command.check(cfg)
        # ↑ 检查。

        engine = create_engine(integration_database_url, isolation_level="AUTOCOMMIT")
        # ↑ 建引擎。
        try:
            # ↑ 尝试。
            tables = _tables_in_schema(engine, test_schema_name)
            # ↑ 列出表。
            assert "integration_extra" in tables
            # ↑ 断言 extra 在。
            cols = _column_info(engine, test_schema_name, "integration_extra")
            # ↑ 读 extra 表的列信息。
            cols_by_name = {c["column_name"]: c for c in cols}
            # ↑ 建索引。
            assert cols_by_name["id"]["is_identity"] == "YES"
            # ↑ 断言主键是 identity。
            assert cols_by_name["description"]["is_nullable"] == "NO"
            # ↑ 断言 description 不可空。
        finally:
            # ↑ 最后。
            engine.dispose()
            # ↑ 释放引擎。

        # --- 第二轮 downgrade：extra 表消失，其余保留 ---
        # ↑ 说明。
        command.downgrade(cfg, "-1")
        # ↑ 降级一步。
        engine = create_engine(integration_database_url, isolation_level="AUTOCOMMIT")
        # ↑ 建引擎。
        try:
            # ↑ 尝试。
            tables = _tables_in_schema(engine, test_schema_name)
            # ↑ 列出表。
            assert "integration_extra" not in tables
            # ↑ 断言 extra 没了。
            assert "integration_entity" in tables
            # ↑ 断言主表还在（只回退了第二步）。
        finally:
            # ↑ 最后。
            engine.dispose()
            # ↑ 释放引擎。
    finally:
        # ↑ 最外层清理。
        _models.set_active_metadata(None)
        # ↑ 恢复完整默认 metadata。


# ---------------------------------------------------------------------------
# version_locations 是临时目录：结束后必须空
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测临时目录不污染仓库。


def test_versions_directory_does_not_pollute_repo(
    # ↑ 测试：生成的迁移文件不落入仓库的 alembic/versions/。
    integration_database_url: str,
    clean_schema: None,
    alembic_workspace: Path,
) -> None:
    """生成的 revision 文件必须落在 ``tmp_path/versions``，不进 ``alembic/versions/``。"""
    # ↑ docstring。
    from alembic import command
    # ↑ 函数内导入。

    cfg = _make_config(alembic_workspace)
    # ↑ 构造配置。
    command.revision(cfg, message="it: pollution check", autogenerate=True)
    # ↑ 生成一份迁移（会落在临时目录）。

    repo_alembic_versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    # ↑ 定位仓库里正式的 alembic/versions 目录。
    py_files = list(repo_alembic_versions.glob("*.py"))
    # ↑ 列出里面的 .py 文件。
    # 仓库 ``alembic/versions/`` 里只能有 ``.gitkeep``，没有 ``.py`` 文件。
    # ↑ 说明。
    assert not py_files, f"alembic/versions/ 被污染：{py_files}"
    # ↑ 断言仓库目录里没有任何 .py 文件（迁移文件都进临时目录了）。
