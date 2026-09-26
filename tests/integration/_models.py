"""Integration test ORM models.

使用独立 ``DeclarativeBase`` 与 ``MetaData``，**不**与 ``app.db.base.Base`` 共享：
避免与 unit tests / ``examples/`` 之间的元数据相互污染。
所有表固定到 ``fastapi_template_test`` Schema，运维侧不会误改其他对象。
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    MetaData,
    String,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 与 ``app.db.base.NAMING_CONVENTION`` 保持一致；测试中重读一遍，避免两边分叉。
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class IntegrationBase(DeclarativeBase):
    metadata = MetaData(
        schema="fastapi_template_test",
        naming_convention=NAMING_CONVENTION,
    )


class IntegrationEntity(IntegrationBase):
    """演示 ``Identity`` 主键 + ``NOT NULL`` + ``UNIQUE`` + 可空 + Check。"""

    __tablename__ = "integration_entity"
    __table_args__ = (
        CheckConstraint("optional_value <> 'forbidden_value'", name="ck_optional_value"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False),
        primary_key=True,
        comment="主键，IDENTITY 自增",
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="必填")
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, comment="必填且唯一")
    optional_value: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="可空")


class IntegrationParent(IntegrationBase):
    """FK 测试用 Parent。"""

    __tablename__ = "integration_parent"
    id: Mapped[int] = mapped_column(Identity(always=False), primary_key=True)


class IntegrationChild(IntegrationBase):
    """FK 测试用 Child；``parent_id`` 引用 ``integration_parent.id``。"""

    __tablename__ = "integration_child"
    id: Mapped[int] = mapped_column(Identity(always=False), primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("integration_parent.id"), nullable=False)


class IntegrationExtra(IntegrationBase):
    """增量 migration 测试用：第二轮 autogenerate 应该产生新表。"""

    __tablename__ = "integration_extra"
    id: Mapped[int] = mapped_column(Identity(always=False), primary_key=True)
    description: Mapped[str] = mapped_column(String(200), nullable=False)


# ---------------------------------------------------------------------------
# 阶段化 metadata：让测试可以控制“当前 Alembic 应该看到哪些表”。
#
# ``_alembic/env.py`` 每次被 alembic exec 时都会调用 ``active_metadata()``，
# 因此测试在两轮 revision 之间切换返回值，就能真实模拟
# “第一轮 3 张表 → 第二轮新增第 4 张表”的增量迁移。
# 不这样做的话，IntegrationExtra 从 import 起就在 metadata 里，
# 第一份 migration 会直接建出全部 4 张表，增量测试就成了假阳性。
# ---------------------------------------------------------------------------

_active_metadata: MetaData | None = None


def set_active_metadata(metadata: MetaData | None) -> None:
    """设置当前 Alembic 可见的 metadata；``None`` 恢复为完整默认值。"""
    global _active_metadata
    _active_metadata = metadata


def active_metadata() -> MetaData:
    return _active_metadata if _active_metadata is not None else IntegrationBase.metadata
