"""Alembic 迁移护栏。

``env.py`` 与测试都从这里导入；保持“护栏是否生效”的判断与 ``context`` 解耦，
方便单元测试直接验证逻辑。
"""

from collections.abc import Mapping
from typing import Any

from alembic.util import CommandError


def reject_empty_metadata(*, autogenerate: bool, tables: Mapping[str, Any]) -> None:
    """空 metadata 护栏：autogenerate 不能基于完全空的 metadata 跑。

    防止 alembic 反射不到任何表，把数据库已有表误判成“删除候选”。

    注意：这只能挡住“所有 Model 都没注册”的情况；漏注册单个 Model 时
    它不生效，所以 autogenerate 之后必须人工 review migration。
    """
    if autogenerate and not tables:
        raise CommandError(
            "Base.metadata 为空；autogenerate 会把已有表当作删除候选。"
            "请在 app/models/__init__.py 显式 import 目标 Model 后重试。"
        )
