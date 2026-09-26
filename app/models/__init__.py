"""ORM Model 显式注册入口。

新 Model 在这里 ``from app.models.xxx import Xxx``；Alembic 通过 ``import app.models``
发现所有表，不会扫描文件系统。
"""

__all__: list[str] = []
