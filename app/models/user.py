"""User ORM 教学示例。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"comment": "用户示例表"}

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False),
        primary_key=True,
        comment="用户主键ID",
    )
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, comment="用户名")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="名称")
    email: Mapped[str | None] = mapped_column(String(254), nullable=True, comment="邮箱")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )
