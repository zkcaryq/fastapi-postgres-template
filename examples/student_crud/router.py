"""教学示例：路由层只做依赖注入与 HTTP 状态码映射。

业务逻辑 / 事务边界都在 Service 层；这里不存在 ``try/except`` 之外的业务判断。
"""
# ↑ 模块 docstring：这个文件是"路由层"，只负责接收 HTTP 请求、调 Service、
#   把业务异常翻译成 HTTP 状态码，不写业务逻辑。

# 从 typing 导入 Annotated（给类型附加元信息）。
from typing import Annotated

# 导入 FastAPI 的路由和参数工具：
#   APIRouter 创建路由组；HTTPException 抛 HTTP 错误；Path/Query 校验参数；Response 通用响应。
from fastapi import APIRouter, HTTPException, Path, Query, Response

# 导入依赖注入类型（拿数据库 Session 用）。
from app.api.dependencies import DbSession

# 导入 service 模块（业务逻辑层）。
from examples.student_crud import service

# 导入三个 Schema（创建、响应、更新的数据结构）。
from examples.student_crud.schema import StuCreate, StuResponse, StuUpdate

router = APIRouter(tags=["stu_table"])
# ↑ 创建路由组，在文档里归到 stu_table 分组。
StuId = Annotated[int, Path(gt=0)]
# ↑ 定义一个"路径参数类型"：整数，且必须大于 0（gt=greater than）。
#   用在 /students/{stu_id} 里，stu_id 会自动校验为正整数。


@router.post("/students", response_model=StuResponse, status_code=201)
# ↑ 声明 POST /students 接口：响应模型是 StuResponse，成功状态码 201（已创建）。
async def create_student(payload: StuCreate, session: DbSession):
    # ↑ 处理函数：payload 是请求体（自动按 StuCreate 校验），session 是注入的数据库会话。

    try:
        # ↑ 尝试调用业务层。
        return await service.create_student(session, payload)
        # ↑ 调 Service 创建，返回创建好的对象（FastAPI 自动转成 StuResponse）。
    except service.DataConflict as exc:
        # ↑ 如果发生"数据冲突"业务异常……
        raise HTTPException(status_code=409, detail=str(exc)) from exc
        # ↑ 转成 409（冲突）状态码返回。


@router.get("/students", response_model=list[StuResponse])
# ↑ 声明 GET /students 接口：返回 StuResponse 的列表。
async def list_students(
    # ↑ 列表查询处理函数。
    session: DbSession,
    # ↑ 注入数据库会话。
    offset: Annotated[int, Query(ge=0)] = 0,
    # ↑ 查询参数 offset：整数，≥0，默认 0（跳过多少条）。
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    # ↑ 查询参数 limit：整数，1~100，默认 20（返回多少条）。
):
    return await service.list_students(session, offset, limit)
    # ↑ 调 Service 查询列表，直接返回。


@router.get("/students/{stu_id}", response_model=StuResponse)
# ↑ 声明 GET /students/{stu_id} 接口：路径里有 stu_id。
async def get_student(stu_id: StuId, session: DbSession):
    # ↑ 处理函数：stu_id 是路径参数（自动校验为正整数）。

    entity = await service.get_student(session, stu_id)
    # ↑ 调 Service 查询单个学生。
    if entity is None:
        # ↑ 没找到……
        raise HTTPException(status_code=404, detail="学生不存在")
        # ↑ 抛 404。
    return entity
    # ↑ 找到就返回。


@router.patch("/students/{stu_id}", response_model=StuResponse)
# ↑ 声明 PATCH /students/{stu_id} 接口（部分更新）。
async def update_student(stu_id: StuId, payload: StuUpdate, session: DbSession):
    # ↑ 处理函数：路径参数 stu_id + 请求体 payload + 数据库会话。

    try:
        # ↑ 尝试更新。
        entity = await service.update_student(session, stu_id, payload)
        # ↑ 调 Service 更新。
    except service.DataConflict as exc:
        # ↑ 数据冲突……
        raise HTTPException(status_code=409, detail=str(exc)) from exc
        # ↑ 转 409。
    if entity is None:
        # ↑ 如果返回 None（学生不存在）……
        raise HTTPException(status_code=404, detail="学生不存在")
        # ↑ 抛 404。
    return entity
    # ↑ 返回更新后的对象。


@router.delete("/students/{stu_id}", status_code=204)
# ↑ 声明 DELETE /students/{stu_id} 接口：成功状态码 204（无内容）。
async def delete_student(stu_id: StuId, session: DbSession):
    # ↑ 处理函数。

    if not await service.delete_student(session, stu_id):
        # ↑ 调 Service 删除，返回 False 表示没找到。
        raise HTTPException(status_code=404, detail="学生不存在")
        # ↑ 没找到抛 404。
    return Response(status_code=204)
    # ↑ 删除成功，返回空响应（204 无内容）。
