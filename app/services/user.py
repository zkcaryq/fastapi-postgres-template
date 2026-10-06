"""User 查询服务。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_user_by_username(
    session: AsyncSession,
    *,
    username: str,
) -> User | None:
    """按用户名查询；Session 由 Router 通过依赖注入传入。"""

    statement = select(User).where(User.username == username)
    return await session.scalar(statement)
