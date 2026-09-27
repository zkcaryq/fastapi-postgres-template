"""Alembic 迁移护栏。

``env.py`` 与测试都从这里导入；保持"护栏是否生效"的判断与 ``context`` 解耦，
方便单元测试直接验证逻辑。
"""
# ↑ 模块 docstring：这个文件放了一个"安全护栏"函数，防止你在一个模型都没注册时
#   就误跑迁移，把数据库里的表全删掉。

# 从 collections.abc 导入 Mapping（映射类型的抽象基类，用于类型标注）。
from collections.abc import Mapping

# 从 typing 导入 Any（表示任意类型）。
from typing import Any

# 从 Alembic 导入 CommandError（Alembic 专用的命令错误异常）。
from alembic.util import CommandError


def reject_empty_metadata(*, autogenerate: bool, tables: Mapping[str, Any]) -> None:
    # ↑ 护栏函数。注意 `*` 后面的参数是"仅限关键字参数"，调用时必须写参数名。
    #   autogenerate：本次是否是"自动生成迁移"模式。
    #   tables：当前注册的所有表（来自 Base.metadata.tables）。

    """空 metadata 护栏：autogenerate 不能基于完全空的 metadata 跑。

    防止 alembic 反射不到任何表，把数据库已有表误判成"删除候选"。

    注意：这只能挡住"所有 Model 都没注册"的情况；漏注册单个 Model 时
    它不生效，所以 autogenerate 之后必须人工 review migration。
    """
    # ↑ docstring：解释这个护栏的作用和局限。

    if autogenerate and not tables:
        # ↑ 如果是"自动生成"模式，且一张表都没注册（tables 为空）……
        raise CommandError(
            # ↑ 抛出 Alembic 命令错误，阻止这次操作。
            "Base.metadata 为空；autogenerate 会把已有表当作删除候选。"
            # ↑ 错误信息第一句。
            "请在 app/models/__init__.py 显式 import 目标 Model 后重试。"
            # ↑ 错误信息第二句（Python 会自动拼接相邻的两个字符串）。
        )
    # ↑ 如果没有触发 raise，函数就正常结束（不拦截）。
