"""教学示例：业务编排 + 事务边界。

Service 不依赖 FastAPI 的 ``HTTPException`` / ``Depends``，
由 Router 把业务异常映射成具体的 HTTP 状态码。
"""
# ↑ 模块 docstring：这个文件是"业务逻辑层"，负责真正的数据操作和事务控制。

# 从 SQLAlchemy 导入 select（构造查询用）。
from sqlalchemy import select

# 导入 SQLAlchemy 异常：IntegrityError（约束冲突）、SQLAlchemyError（异常基类）。
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

# 导入 AsyncSession（异步数据库会话类型）。
from sqlalchemy.ext.asyncio import AsyncSession

# 导入学生表模型（ORM 类）。
from examples.student_crud.model import StuTable

# 导入创建和更新用的 Schema（请求数据结构）。
from examples.student_crud.schema import StuCreate, StuUpdate


class DataConflict(Exception):
    # ↑ 自定义一个"数据冲突"业务异常（比如唯一键重复）。

    """数据库约束冲突；Router 决定对应的 HTTP 状态。"""

    # ↑ docstring：说明这个异常最后由 Router 翻译成 HTTP 状态码。


async def _commit(session: AsyncSession) -> None:
    # ↑ 统一的提交入口（下划线开头表示内部使用）。所有写操作都走这里提交。

    """统一 commit 入口：失败先 rollback 再抛业务异常。

    SQLSTATE 是数据库的稳定错误码；不要解析英文错误文本，
    也别把数据库原始错误原样抛给客户端。
    """
    # ↑ docstring：解释为什么统一提交、为什么要用 SQLSTATE 判断错误。

    try:
        # ↑ 尝试提交事务。
        await session.commit()
        # ↑ 提交（真正把改动写进数据库）。
    except SQLAlchemyError as exc:
        # ↑ 如果提交时发生数据库错误……
        await session.rollback()
        # ↑ 先回滚，撤销本次事务的所有改动（防止 Session 卡在坏状态）。
        if isinstance(exc, IntegrityError):
            # ↑ 如果是"约束冲突"类错误……
            code = getattr(exc.orig, "sqlstate", None)
            # ↑ 取出数据库返回的 SQLSTATE 标准错误码（如 23505）。
            #   exc.orig 是底层驱动抛的原始异常，sqlstate 是它的属性。
            if code == "23505":
                # ↑ 23505 = 唯一约束冲突。
                raise DataConflict("唯一字段已存在") from exc
                # ↑ 转成业务异常抛出，并把原始异常挂在链上（from exc）。
            if code == "23503":
                # ↑ 23503 = 外键约束冲突。
                raise DataConflict("关联记录不存在或仍被引用") from exc
                # ↑ 转成业务异常。
            if code == "23514":
                # ↑ 23514 = 检查约束冲突。
                raise DataConflict("数据违反检查约束") from exc
                # ↑ 转成业务异常。
            if code == "23502":
                # ↑ 23502 = NOT NULL 约束冲突。
                # 数据库最后一道保护：Schema 应已挡住显式 null。
                # 走到这里说明 Schema 校验与 DB 约束不一致，应视为代码 bug。
                # ↑ 说明：正常情况 Schema 层已经拦住显式 null，能走到这属于代码 bug。
                raise DataConflict("字段为 NOT NULL 但收到了 null") from exc
                # ↑ 转成业务异常。
        raise
        # ↑ 不是 IntegrityError（其他数据库错误）：原样往上抛，交给兜底中间件。


async def create_student(session: AsyncSession, payload: StuCreate) -> StuTable:
    # ↑ 创建学生：接收 Session 和"创建"数据，返回新创建的学生对象。

    entity = StuTable(**payload.model_dump())
    # ↑ 把 Schema 数据转成字典，用 ** 展开成关键字参数，构造一个 StuTable 对象。
    #   model_dump() 把校验过的数据导出成普通字典。
    session.add(entity)
    # ↑ 把新对象加入 Session（标记为"待插入"，尚未发 SQL）。
    await _commit(session)
    # ↑ 提交事务（真正执行 INSERT）。
    return entity
    # ↑ 返回这个对象（此时已写入数据库）。


async def list_students(session: AsyncSession, offset: int = 0, limit: int = 20) -> list[StuTable]:
    # ↑ 分页查询学生列表：offset 是跳过条数，limit 是返回条数。

    result = await session.scalars(
        # ↑ 执行查询并返回"标量结果"（这里是多个 StuTable 对象）。
        select(StuTable).order_by(StuTable.stu_id).offset(offset).limit(limit)
        # ↑ 构造查询：查 StuTable 表，按 stu_id 排序，跳过 offset 条，取 limit 条。
    )
    return list(result.all())
    # ↑ 把结果转成列表返回（.all() 取出全部，list() 转成 Python 列表）。


async def get_student(session: AsyncSession, stu_id: int) -> StuTable | None:
    # ↑ 按主键查单个学生，找不到返回 None。

    return await session.get(StuTable, stu_id)
    # ↑ session.get() 是按主键查询的快捷方法，找到返回对象，找不到返回 None。


async def update_student(session: AsyncSession, stu_id: int, payload: StuUpdate) -> StuTable | None:
    # ↑ 更新学生：先查出来，改字段，再提交。找不到返回 None。

    entity = await session.get(StuTable, stu_id)
    # ↑ 按主键查出要更新的学生。
    if entity is None:
        # ↑ 如果不存在……
        return None
        # ↑ 返回 None（Router 会转成 404）。
    # exclude_unset=True 决定"未传字段不进字典"：写操作只针对客户端明确给出的字段。
    # model_fields_set 在 Schema 层已被用于挡住对 NOT NULL 列的显式 null。
    # ↑ 说明：只更新客户端明确给出的字段。
    for field, value in payload.model_dump(exclude_unset=True).items():
        # ↑ 遍历"本次请求里明确给出的字段"（exclude_unset=True 排除未传字段）。
        setattr(entity, field, value)
        # ↑ 把字段的新值赋给对象（setattr 按名字设置属性）。
    await _commit(session)
    # ↑ 提交事务（执行 UPDATE）。
    return entity
    # ↑ 返回更新后的对象。


async def delete_student(session: AsyncSession, stu_id: int) -> bool:
    # ↑ 删除学生：返回 True（删成功）或 False（不存在）。

    entity = await session.get(StuTable, stu_id)
    # ↑ 查出要删的学生。
    if entity is None:
        # ↑ 不存在……
        return False
        # ↑ 返回 False。
    await session.delete(entity)
    # ↑ 标记删除（真正 DELETE 在 commit 时执行）。
    await _commit(session)
    # ↑ 提交事务（执行 DELETE）。
    return True
    # ↑ 返回 True 表示删除成功。
