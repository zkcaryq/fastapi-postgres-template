"""示例业务层：负责查询和事务，不依赖 FastAPI 的 HTTPException / Depends。"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student import StuTable
from app.schemas.student import StuCreate, StuUpdate


class DataConflict(Exception):
    """示例写入违反数据库约束；Router 决定对应的 HTTP 状态。"""


async def _commit(session: AsyncSession) -> None:
    # commit 自带 flush；只有要中途取主键或检查约束时才单独 await flush()。
    # 一个完整业务只在明确边界提交；不要把自动 commit 放进 dependency。
    try:
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        # SQLSTATE 直接拿来判断，不解析英文错误文本，也不把数据库错误原样抛给客户端。
        if isinstance(exc, IntegrityError):
            code = getattr(exc.orig, "sqlstate", None)
            if code == "23505":
                raise DataConflict("唯一字段已存在") from exc
            if code == "23503":
                raise DataConflict("关联记录不存在或仍被引用") from exc
            if code == "23514":
                raise DataConflict("数据违反检查约束") from exc
        raise


async def create_student(session: AsyncSession, payload: StuCreate) -> StuTable:
    entity = StuTable(**payload.model_dump())
    session.add(entity)  # add 只登记对象，不是异步 I/O。
    await _commit(session)
    return entity


async def list_students(
    session: AsyncSession, offset: int = 0, limit: int = 20
) -> list[StuTable]:
    result = await session.scalars(
        select(StuTable).order_by(StuTable.stu_id).offset(offset).limit(limit)
    )
    return list(result.all())


async def get_student(session: AsyncSession, stu_id: int) -> StuTable | None:
    return await session.get(StuTable, stu_id)


async def update_student(
    session: AsyncSession, stu_id: int, payload: StuUpdate
) -> StuTable | None:
    entity = await session.get(StuTable, stu_id)
    if entity is None:
        return None
    # exclude_unset 区分“未传”与“显式 null”。
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