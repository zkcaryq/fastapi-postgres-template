from app.models.student import StuTable

# 显式 import 才能让 Base.metadata 看到这张表；Alembic 也通过这个包发现表。
__all__ = ["StuTable"]