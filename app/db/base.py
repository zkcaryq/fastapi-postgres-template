"""ORM 基类与命名约定：所有数据模型（表）都继承这里的 Base。"""
# ↑ 模块 docstring：这个文件定义了 ORM 的"根"，所有表定义都从这里继承。

# 从 SQLAlchemy 导入 MetaData（元数据，管理所有表的集合信息）。
from sqlalchemy import MetaData

# 从 SQLAlchemy 的 ORM 模块导入 DeclarativeBase（声明式 ORM 的基类）。
from sqlalchemy.orm import DeclarativeBase

# 导入配置读取函数（因为要给表统一指定 Schema）。
from app.core.settings import get_settings

# 多字段约束使用所有字段，避免只取第一列造成名称碰撞。
# CheckConstraint 必须显式提供 name，尤其是直接写 SQL 字符串时。
# ↑ 设计说明：这是"命名约定"的规则说明。
NAMING_CONVENTION = {
    # ↑ 定义一个字典：约束/索引的统一命名模板。
    #   让每个约束的名字都可预测（比如唯一约束固定叫 uq_表名_列名），
    #   这样 Alembic 迁移时能稳定地找到并操作它们。
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    # ↑ 索引（index）命名：ix_表名_列名。
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    # ↑ 唯一约束（unique）命名：uq_表名_列名。
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    # ↑ 检查约束（check）命名：ck_表名_约束名。
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    # ↑ 外键（foreign key）命名：fk_表名_列名_引用表名。
    "pk": "pk_%(table_name)s",
    # ↑ 主键（primary key）命名：pk_表名。
}


class Base(DeclarativeBase):
    # ↑ 定义 ORM 基类。所有 Model 都继承它，从而共享下面的 metadata 配置。

    # 所有 Model 继承同一 Base，自动继承用户指定的 Schema。
    # 不使用 create_all：结构变更必须有可审阅、可追踪的 Alembic 迁移。
    # ↑ 设计说明：表自动归属指定 Schema；且不用 create_all 建表（交给 Alembic）。
    metadata = MetaData(
        # ↑ 创建一个 MetaData 对象，作为所有表的"登记册"。
        schema=get_settings().DB_SCHEMA,
        # ↑ 指定 Schema：所有继承 Base 的表都会自动带上这个 Schema（如 app）。
        naming_convention=NAMING_CONVENTION,
        # ↑ 应用上面的命名约定。
    )
