"""教学示例：路由层只做依赖注入与 HTTP 状态码映射。

业务逻辑 / 事务边界都在 Service 层；这里不存在 ``try/except`` 之外的业务判断。
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Response

from app.api.dependencies import DbSession
from examples.student_crud import service
from examples.student_crud.schema import StuCreate, StuResponse, StuUpdate

router = APIRouter(tags=["stu_table"])
StuId = Annotated[int, Path(gt=0)]


@router.post("/students", response_model=StuResponse, status_code=201)
async def create_student(payload: StuCreate, session: DbSession):
    try:
        return await service.create_student(session, payload)
    except service.DataConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/students", response_model=list[StuResponse])
async def list_students(
    session: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return await service.list_students(session, offset, limit)


@router.get("/students/{stu_id}", response_model=StuResponse)
async def get_student(stu_id: StuId, session: DbSession):
    entity = await service.get_student(session, stu_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="学生不存在")
    return entity


@router.patch("/students/{stu_id}", response_model=StuResponse)
async def update_student(stu_id: StuId, payload: StuUpdate, session: DbSession):
    try:
        entity = await service.update_student(session, stu_id, payload)
    except service.DataConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if entity is None:
        raise HTTPException(status_code=404, detail="学生不存在")
    return entity


@router.delete("/students/{stu_id}", status_code=204)
async def delete_student(stu_id: StuId, session: DbSession):
    if not await service.delete_student(session, stu_id):
        raise HTTPException(status_code=404, detail="学生不存在")
    return Response(status_code=204)
