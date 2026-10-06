"""显式导入所有 ORM Model，确保 Alembic 能发现对应表。"""

from app.models.user import User

__all__ = ["User"]
