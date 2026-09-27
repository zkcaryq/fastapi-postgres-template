"""Integration test ORM models.

使用独立 ``DeclarativeBase`` 与 ``MetaData``，**不**与 ``app.db.base.Base`` 共享：
避免与 unit tests / ``examples/`` 之间的元数据相互污染。
所有表固定到 ``fastapi_template_test`` Schema，运维侧不会误改其他对象。
"""
# ↑ 模块 docstring：集成测试用"独立的 ORM 基类"和"独立的表"，避免污染正式代码。
#   所有表都固定在一个测试专用 Schema（fastapi_template_test）里。

# 从 SQLAlchemy 导入多种类型（多行 import，用括号包裹）。
from sqlalchemy import (
    BigInteger,  # 大整数类型
    CheckConstraint,  # 检查约束
    ForeignKey,  # 外键
    Identity,  # 自增主键
    MetaData,  # 元数据（表集合）
    String,  # 字符串类型
)

# 导入 SQLAlchemy 2 的 ORM 写法。
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 与 ``app.db.base.NAMING_CONVENTION`` 保持一致；测试中重读一遍，避免两边分叉。
# ↑ 说明：命名约定要和正式代码一致，但这里单独写一份，避免测试和正式代码耦合。
NAMING_CONVENTION = {
    # ↑ 命名约定字典（和 app/db/base.py 里的一致）。
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    # ↑ 索引命名。
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    # ↑ 唯一约束命名。
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    # ↑ 检查约束命名。
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    # ↑ 外键命名。
    "pk": "pk_%(table_name)s",
    # ↑ 主键命名。
}


class IntegrationBase(DeclarativeBase):
    # ↑ 测试专用的 ORM 基类（独立于正式代码的 Base）。

    metadata = MetaData(
        # ↑ 创建元数据。
        schema="fastapi_template_test",
        # ↑ 所有测试表都固定在测试 Schema。
        naming_convention=NAMING_CONVENTION,
        # ↑ 应用命名约定。
    )


class IntegrationEntity(IntegrationBase):
    # ↑ 测试主表：演示 Identity 主键 + NOT NULL + UNIQUE + 可空 + Check。

    """演示 ``Identity`` 主键 + ``NOT NULL`` + ``UNIQUE`` + 可空 + Check。"""

    # ↑ docstring。

    __tablename__ = "integration_entity"
    # ↑ 表名。

    __table_args__ = (
        # ↑ 表级约束。
        CheckConstraint("optional_value <> 'forbidden_value'", name="ck_optional_value"),
        # ↑ 一个检查约束：optional_value 不能等于 'forbidden_value'。
    )

    id: Mapped[int] = mapped_column(
        # ↑ 主键列。
        BigInteger,
        # ↑ 大整数。
        Identity(always=False),
        # ↑ 自增主键（BY DEFAULT）。
        primary_key=True,
        # ↑ 主键。
        comment="主键，IDENTITY 自增",
        # ↑ 注释。
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="必填")
    # ↑ 姓名字段：必填。
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, comment="必填且唯一")
    # ↑ 编号字段：必填且唯一。
    optional_value: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="可空")
    # ↑ 可空字段。


class IntegrationParent(IntegrationBase):
    # ↑ 父表（用于外键测试）。

    """FK 测试用 Parent。"""

    # ↑ docstring。

    __tablename__ = "integration_parent"
    # ↑ 表名。
    id: Mapped[int] = mapped_column(Identity(always=False), primary_key=True)
    # ↑ 主键。


class IntegrationChild(IntegrationBase):
    # ↑ 子表（用于外键测试）。

    """FK 测试用 Child；``parent_id`` 引用 ``integration_parent.id``。"""

    # ↑ docstring。

    __tablename__ = "integration_child"
    # ↑ 表名。
    id: Mapped[int] = mapped_column(Identity(always=False), primary_key=True)
    # ↑ 主键。
    parent_id: Mapped[int] = mapped_column(ForeignKey("integration_parent.id"), nullable=False)
    # ↑ 外键列：引用 integration_parent.id，必填。


class IntegrationExtra(IntegrationBase):
    # ↑ 额外表（用于增量迁移测试）。

    """增量 migration 测试用：第二轮 autogenerate 应该产生新表。"""

    # ↑ docstring。

    __tablename__ = "integration_extra"
    # ↑ 表名。
    id: Mapped[int] = mapped_column(Identity(always=False), primary_key=True)
    # ↑ 主键。
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    # ↑ 描述字段：必填。


# ---------------------------------------------------------------------------
# 阶段化 metadata：让测试可以控制"当前 Alembic 应该看到哪些表"。
#
# ``_alembic/env.py`` 每次被 alembic exec 时都会调用 ``active_metadata()``，
# 因此测试在两轮 revision 之间切换返回值，就能真实模拟
# "第一轮 3 张表 → 第二轮新增第 4 张表"的增量迁移。
# 不这样做的话，IntegrationExtra 从 import 起就在 metadata 里，
# 第一份 migration 会直接建出全部 4 张表，增量测试就成了假阳性。
# ---------------------------------------------------------------------------
# ↑ 大段说明：解释下面"阶段化 metadata"机制的用途。

_active_metadata: MetaData | None = None
# ↑ 一个全局变量，存"当前 Alembic 应该看到的表集合"。None 表示用完整默认值。


def set_active_metadata(metadata: MetaData | None) -> None:
    # ↑ 设置当前可见的 metadata。

    """设置当前 Alembic 可见的 metadata；``None`` 恢复为完整默认值。"""
    # ↑ docstring。
    global _active_metadata
    # ↑ 声明要修改全局变量。
    _active_metadata = metadata
    # ↑ 赋值。


def active_metadata() -> MetaData:
    # ↑ 返回当前可见的 metadata。

    return _active_metadata if _active_metadata is not None else IntegrationBase.metadata
    # ↑ 如果设了阶段性 metadata 就用它，否则用完整默认值（所有表）。
