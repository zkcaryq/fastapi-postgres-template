"""依赖注入：定义路由里可直接声明的数据库会话类型。"""
# ↑ 模块 docstring：这个文件很小，只定义一个"快捷类型"。

# 从 typing 导入 Annotated（给类型附加额外元信息的工具）。
from typing import Annotated

# 从 FastAPI 导入 Depends（声明依赖的标记）。
from fastapi import Depends

# 从 SQLAlchemy 导入 AsyncSession（异步会话类型）。
from sqlalchemy.ext.asyncio import AsyncSession

# 导入依赖注入函数（负责创建和关闭 Session）。
from app.db.session import get_db_session

# 路由只声明依赖；不让 Service 依赖 FastAPI 的 Depends 或 HTTPException。
# ↑ 设计说明：依赖只在这一层声明，Service 层保持"不依赖 FastAPI"的纯净。
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
# ↑ 定义一个"带依赖的类型"：DbSession 本质是 AsyncSession 类型，
#   但附带了 Depends(get_db_session) 这个元信息。
#   这样路由函数参数写成 `session: DbSession`，FastAPI 就会自动调用
#   get_db_session 来创建并注入 Session，用完自动关闭。
