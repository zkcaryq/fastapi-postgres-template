"""Alembic 空 metadata 护栏。

模板运行时 ``app/models/__init__.py`` 是空的（``__all__: list[str] = []``）；
``Base.metadata.tables`` 自然也是空的。这条护栏挡住 ``alembic revision
--autogenerate`` 在 metadata 完全空时把现有表误判为删除。
"""

import pytest
from alembic.util import CommandError

from app.db.alembic_guard import reject_empty_metadata


def test_reject_empty_metadata_blocks_autogenerate_when_empty():
    with pytest.raises(CommandError, match="Base.metadata 为空"):
        reject_empty_metadata(autogenerate=True, tables={})


def test_reject_empty_metadata_allows_non_autogenerate_when_empty():
    """``alembic current`` / ``alembic heads`` 这类不需要 autogenerate 的命令不被拦。"""
    reject_empty_metadata(autogenerate=False, tables={})


def test_reject_empty_metadata_allows_autogenerate_with_models():
    """只要有任意一个 Model 注册，autogenerate 就应该被允许。"""
    reject_empty_metadata(autogenerate=True, tables={"some_table": object()})
