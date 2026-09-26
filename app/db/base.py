from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from app.core.settings import get_settings

# 多字段约束使用所有字段，避免只取第一列造成名称碰撞。
# CheckConstraint 必须显式提供 name，尤其是直接写 SQL 字符串时。
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    # 所有 Model 继承同一 Base，自动继承用户指定的 Schema。
    # 不使用 create_all：结构变更必须有可审阅、可追踪的 Alembic 迁移。
    metadata = MetaData(
        schema=get_settings().DB_SCHEMA,
        naming_convention=NAMING_CONVENTION,
    )
