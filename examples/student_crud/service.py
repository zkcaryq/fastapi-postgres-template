"""教学示例：业务编排 + 事务边界。

Service 不依赖 FastAPI 的 ``HTTPException`` / ``Depends``，
由 Router 把业务异常映射成具体的 HTTP 状态码。
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from examples.student_crud.model import StuTable
from examples.student_crud.schema import StuCreate, StuUpdate


class DataConflict(Exception):
    """数据库约束冲突；Router 决定对应的 HTTP 状态。"""


async def _commit(session: AsyncSession) -> None:
    """统一 commit 入口：失败先 rollback 再抛业务异常。

    SQLSTATE 是数据库的稳定错误码；不要解析英文错误文本，
    也别把数据库原始错误原样抛给客户端。
    """
    try:
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        if isinstance(exc, IntegrityError):
            code = getattr(exc.orig, "sqlstate", None)
            if code == "23505":
                raise DataConflict("唯一字段已存在") from exc
            if code == "23503":
                raise DataConflict("关联记录不存在或仍被引用") from exc
            if code == "23514":
                raise DataConflict("数据违反检查约束") from exc
            if code == "23502":
                # 数据库最后一道保护：Schema 应已挡住显式 null。
                # 走到这里说明 Schema 校验与 DB 约束不一致，应视为代码 bug。
                raise DataConflict("字段为 NOT NULL 但收到了 null") from exc
        raise


async def create_student(session: AsyncSession, payload: StuCreate) -> StuTable:
    entity = StuTable(**payload.model_dump())
    session.add(entity)
    await _commit(session)
    return entity


async def list_students(session: AsyncSession, offset: int = 0, limit: int = 20) -> list[StuTable]:
    result = await session.scalars(
        select(StuTable).order_by(StuTable.stu_id).offset(offset).limit(limit)
    )
    return list(result.all())


async def get_student(session: AsyncSession, stu_id: int) -> StuTable | None:
    return await session.get(StuTable, stu_id)


async def update_student(session: AsyncSession, stu_id: int, payload: StuUpdate) -> StuTable | None:
    entity = await session.get(StuTable, stu_id)
    if entity is None:
        return None
    # exclude_unset=True 决定“未传字段不进字典”：写操作只针对客户端明确给出的字段。
    # model_fields_set 在 Schema 层已被用于挡住对 NOT NULL 列的显式 null。
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entity, field, value)
    await _commit(session)
    return entity


async def delete_student(session: AsyncSession, stu_id: int) -> bool:
    entity = await session.get(StuTable, stu_id)
    if entity is None:
        return False
    await session.delete(entity)
    await _commit(session)
    return True
