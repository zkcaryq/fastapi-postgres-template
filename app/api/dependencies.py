from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session

# 路由只声明依赖；不让 Service 依赖 FastAPI 的 Depends 或 HTTPException。
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
