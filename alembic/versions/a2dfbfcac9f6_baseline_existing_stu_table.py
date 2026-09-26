"""baseline: existing stu_table

Revision ID: a2dfbfcac9f6
Revises:
Create Date: 2026-09-26 23:05:23.954551

说明：
- 这是一条空迁移。test.stu_table 由已有脚本手动建立，模板接管时不重建、不删数据。
- 升级 / 降级都是 pass；它的作用是在 alembic_version 表里登记当前数据库的迁移基线。
- 新增字段、索引、约束时再创建下一条 revision。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a2dfbfcac9f6'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
