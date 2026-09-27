"""Alembic 空 metadata 护栏。

模板运行时 ``app/models/__init__.py`` 是空的（``__all__: list[str] = []``）；
``Base.metadata.tables`` 自然也是空的。这条护栏挡住 ``alembic revision
--autogenerate`` 在 metadata 完全空时把现有表误判为删除。
"""
# ↑ 模块 docstring：这个文件测试"空 metadata 护栏"函数的行为。
#   护栏的作用：防止你在一张表都没注册时误跑 autogenerate，把数据库里的表删光。

# 导入 pytest 测试框架。
import pytest

# 导入 Alembic 的 CommandError（护栏抛出的就是这个异常）。
from alembic.util import CommandError

# 导入要测试的护栏函数。
from app.db.alembic_guard import reject_empty_metadata


def test_reject_empty_metadata_blocks_autogenerate_when_empty():
    # ↑ 测试：空 metadata + autogenerate 模式 → 应该被拦截。

    with pytest.raises(CommandError, match="Base.metadata 为空"):
        # ↑ 断言：下面的调用会抛出 CommandError，且错误信息里包含"Base.metadata 为空"。
        reject_empty_metadata(autogenerate=True, tables={})
        # ↑ 传入 autogenerate=True（自动生成）和空表字典（{} 表示一张表都没有）。


def test_reject_empty_metadata_allows_non_autogenerate_when_empty():
    # ↑ 测试：空 metadata 但**不是** autogenerate 模式 → 不应该拦截。

    """``alembic current`` / ``alembic heads`` 这类不需要 autogenerate 的命令不被拦。"""
    # ↑ docstring：说明普通命令（查看版本等）不应该被拦。
    reject_empty_metadata(autogenerate=False, tables={})
    # ↑ 调用后没有抛出异常，测试就通过（pytest 里没有报错即通过）。


def test_reject_empty_metadata_allows_autogenerate_with_models():
    # ↑ 测试：只要注册了任意一个模型，autogenerate 就应该被允许。

    """只要有任意一个 Model 注册，autogenerate 就应该被允许。"""
    # ↑ docstring。
    reject_empty_metadata(autogenerate=True, tables={"some_table": object()})
    # ↑ 传入一个"非空"的表字典（模拟已注册了一个表），不抛异常即通过。
